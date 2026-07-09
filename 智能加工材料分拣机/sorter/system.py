from __future__ import annotations

import copy
import os
import threading
import time
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from .config import load_config, save_config, validate_config
from .devices import DeviceScanner
from .layer import LayerController
from .logstore import LogStore
from .vision import Detector, InferenceScheduler


class SorterSystem:
    """多层分拣系统总管理器。"""

    def __init__(self, config_path: str):
        self.config_path = str(Path(config_path).resolve())
        self.project_dir = str(Path(self.config_path).parent)
        self.config = load_config(self.config_path)
        self.lock = threading.RLock()
        self.started_at = time.time()

        data_dir = Path(self.project_dir) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.log_store = LogStore(str(data_dir / "sorter.db"))
        self.scanner = DeviceScanner(
            int(self.config["system"].get("camera_scan_max_index", 64))
        )
        self.devices: dict[str, list[dict[str, Any]]] = {
            "cameras": [],
            "pwm_channels": [],
        }

        self.detector = Detector(
            model_path=self.config["system"]["model_path"],
            labels_path=self.config["system"]["labels_path"],
            warmup_runs=int(self.config["system"].get("warmup_runs", 10)),
        )
        self.scheduler = InferenceScheduler(self.detector)
        self.layers: dict[str, LayerController] = {}

        self.rescan_devices(probe_cameras=True)
        self._resolve_saved_bindings()
        self._create_layers()
        self.log_store.info("system", "多层分拣系统初始化完成")

    def _create_layers(self) -> None:
        self.layers.clear()
        for layer_config in self.config.get("layers", []):
            layer = LayerController(
                config=layer_config,
                system_config=self.config["system"],
                labels=self.detector.labels,
                scheduler=self.scheduler,
                log_store=self.log_store,
            )
            self.layers[layer.layer_id] = layer

    def _running_camera_paths(self) -> set[str]:
        paths: set[str] = set()
        for layer in self.layers.values():
            snapshot = layer.snapshot()
            if snapshot["state"] in ("RUNNING", "PAUSED") and snapshot.get("camera_path"):
                paths.add(str(snapshot["camera_path"]))
        return paths

    def rescan_devices(self, probe_cameras: bool = True) -> dict[str, Any]:
        with self.lock:
            skip_paths = self._running_camera_paths() if self.layers else set()
            self.devices = self.scanner.scan_all(
                probe_cameras=probe_cameras,
                skip_camera_paths=skip_paths,
            )
            self._resolve_saved_bindings()
            if self.layers:
                self._sync_layer_runtime_bindings()
            self.log_store.info(
                "device",
                "设备扫描完成",
                {
                    "cameras": len(self.devices["cameras"]),
                    "pwm_channels": len(self.devices["pwm_channels"]),
                },
            )
            return copy.deepcopy(self.devices)

    def _resolve_saved_bindings(self) -> None:
        camera_by_uid = {item["uid"]: item for item in self.devices.get("cameras", [])}
        pwm_by_uid = {item["uid"]: item for item in self.devices.get("pwm_channels", [])}

        for layer in self.config.get("layers", []):
            camera_uid = layer.get("camera_uid")
            if camera_uid and camera_uid in camera_by_uid:
                layer["camera_path"] = camera_by_uid[camera_uid]["path"]

            pwm_uid = layer.get("pwm_uid")
            if pwm_uid and pwm_uid in pwm_by_uid:
                layer["pwm_chip"] = pwm_by_uid[pwm_uid]["chip"]
                layer["pwm_channel"] = pwm_by_uid[pwm_uid]["channel"]

    def _sync_layer_runtime_bindings(self) -> None:
        config_by_id = {layer["id"]: layer for layer in self.config.get("layers", [])}
        for layer_id, controller in self.layers.items():
            if layer_id not in config_by_id:
                continue
            if controller.snapshot()["state"] in ("RUNNING", "PAUSED"):
                continue
            controller.update_config(
                {
                    "camera_uid": config_by_id[layer_id].get("camera_uid"),
                    "camera_path": config_by_id[layer_id].get("camera_path"),
                    "pwm_uid": config_by_id[layer_id].get("pwm_uid"),
                    "pwm_chip": config_by_id[layer_id].get("pwm_chip"),
                    "pwm_channel": config_by_id[layer_id].get("pwm_channel"),
                }
            )

    def _layer_config(self, layer_id: str) -> dict[str, Any]:
        for layer in self.config.get("layers", []):
            if layer.get("id") == layer_id:
                return layer
        raise KeyError(f"不存在分拣层: {layer_id}")

    def get_layer(self, layer_id: str) -> LayerController:
        try:
            return self.layers[layer_id]
        except KeyError as error:
            raise KeyError(f"不存在分拣层: {layer_id}") from error

    def _validate_unique_bindings(
        self,
        layer_id: str,
        camera_uid: str | None,
        pwm_uid: str | None,
    ) -> None:
        for other in self.config.get("layers", []):
            if other.get("id") == layer_id:
                continue
            if camera_uid and other.get("camera_uid") == camera_uid:
                raise ValueError(
                    f"摄像头已经绑定到 {other.get('name', other.get('id'))}"
                )
            if pwm_uid and other.get("pwm_uid") == pwm_uid:
                raise ValueError(
                    f"PWM 通道已经绑定到 {other.get('name', other.get('id'))}"
                )

    def update_layer(self, layer_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        updates = copy.deepcopy(updates)
        with self.lock:
            layer_config = self._layer_config(layer_id)

            camera_uid = updates.get("camera_uid", layer_config.get("camera_uid"))
            pwm_uid = updates.get("pwm_uid", layer_config.get("pwm_uid"))
            self._validate_unique_bindings(layer_id, camera_uid, pwm_uid)

            if "camera_uid" in updates:
                camera = next(
                    (
                        item
                        for item in self.devices.get("cameras", [])
                        if item["uid"] == updates["camera_uid"]
                    ),
                    None,
                )
                if updates["camera_uid"] and camera is None:
                    raise ValueError("所选摄像头当前不存在")
                updates["camera_path"] = camera["path"] if camera else None

            if "pwm_uid" in updates:
                pwm = next(
                    (
                        item
                        for item in self.devices.get("pwm_channels", [])
                        if item["uid"] == updates["pwm_uid"]
                    ),
                    None,
                )
                if updates["pwm_uid"] and pwm is None:
                    raise ValueError("所选 PWM 通道当前不存在")
                updates["pwm_chip"] = pwm["chip"] if pwm else None
                updates["pwm_channel"] = pwm["channel"] if pwm else None

            servo_updates = updates.get("servo")
            for key, value in updates.items():
                if key == "servo":
                    continue
                layer_config[key] = value
            if servo_updates is not None:
                layer_config.setdefault("servo", {}).update(servo_updates)

            validate_config(self.config)
            self.layers[layer_id].update_config(updates)
            self.save()
            return self.layers[layer_id].snapshot()

    def set_target_color(
        self,
        layer_id: str,
        target_color: str,
        reset_counts: bool = True,
    ) -> dict[str, Any]:
        with self.lock:
            layer = self.get_layer(layer_id)
            layer.set_target_color(target_color, reset_counts=reset_counts)
            self._layer_config(layer_id)["target_color"] = target_color
            self.save()
            return layer.snapshot()

    def save(self) -> None:
        save_config(self.config_path, self.config)

    def start_layer(self, layer_id: str) -> dict[str, Any]:
        layer = self.get_layer(layer_id)
        layer.start()
        return layer.snapshot()

    def pause_layer(self, layer_id: str) -> dict[str, Any]:
        layer = self.get_layer(layer_id)
        layer.pause()
        return layer.snapshot()

    def resume_layer(self, layer_id: str) -> dict[str, Any]:
        layer = self.get_layer(layer_id)
        layer.resume()
        return layer.snapshot()

    def stop_layer(self, layer_id: str) -> dict[str, Any]:
        layer = self.get_layer(layer_id)
        layer.stop()
        return layer.snapshot()

    def reset_layer_counts(self, layer_id: str) -> dict[str, Any]:
        layer = self.get_layer(layer_id)
        layer.reset_counts()
        return layer.snapshot()

    def manual_action(self, layer_id: str, action: str) -> dict[str, Any]:
        layer = self.get_layer(layer_id)
        layer.manual_action(action)
        return layer.snapshot()

    def start_all(self) -> dict[str, Any]:
        errors: dict[str, str] = {}
        for layer_id, layer in self.layers.items():
            try:
                if layer.snapshot()["enabled"]:
                    layer.start()
            except Exception as error:
                errors[layer_id] = str(error)
                self.log_store.error(layer_id, "启动失败", {"error": str(error)})
        return {"errors": errors, "status": self.status()}

    def pause_all(self) -> dict[str, Any]:
        for layer in self.layers.values():
            layer.pause()
        return self.status()

    def stop_all(self) -> dict[str, Any]:
        for layer in self.layers.values():
            layer.stop()
        return self.status()

    def reset_all_counts(self) -> dict[str, Any]:
        for layer in self.layers.values():
            layer.reset_counts()
        return self.status()

    @staticmethod
    def _temperature_c() -> float | None:
        candidates = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
        values: list[float] = []
        for path in candidates:
            try:
                value = float(path.read_text(encoding="utf-8").strip())
                if value > 1000:
                    value /= 1000.0
                if -20 <= value <= 150:
                    values.append(value)
            except (OSError, ValueError):
                continue
        return round(max(values), 1) if values else None

    def metrics(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "temperature_c": self._temperature_c(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
        }
        if psutil is not None:
            result.update(
                {
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "memory_percent": psutil.virtual_memory().percent,
                    "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
                }
            )
        else:
            result.update(
                {
                    "cpu_percent": None,
                    "memory_percent": None,
                    "load_average": None,
                }
            )
        return result

    def status(self) -> dict[str, Any]:
        layers = [layer.snapshot() for layer in self.layers.values()]
        return {
            "system_name": self.config["system"].get("name", "K1 分拣系统"),
            "time": time.time(),
            "metrics": self.metrics(),
            "layers": layers,
            "summary": {
                "target_count": sum(item["target_count"] for item in layers),
                "other_count": sum(item["other_count"] for item in layers),
                "total_crossings": sum(item["total_crossings"] for item in layers),
                "running_layers": sum(item["state"] == "RUNNING" for item in layers),
                "fault_layers": sum(item["state"] == "FAULT" for item in layers),
            },
        }

    def device_snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.devices)

    def recent_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.log_store.recent(limit)

    def close(self) -> None:
        for layer in self.layers.values():
            try:
                layer.close()
            except Exception as error:
                self.log_store.error("system", "关闭分拣层失败", {"error": str(error)})
        self.scheduler.close()
        self.log_store.info("system", "多层分拣系统已关闭")
