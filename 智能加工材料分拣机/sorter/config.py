from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_COLORS = ("red", "yellow", "blue", "green")
SUPPORTED_NON_TARGET_ACTIONS = ("pass", "other")


def default_layer(layer_id: str, name: str, target_color: str) -> dict[str, Any]:
    return {
        "id": layer_id,
        "name": name,
        "enabled": True,
        "camera_uid": None,
        "camera_path": None,
        "pwm_uid": None,
        "pwm_chip": None,
        "pwm_channel": None,
        "target_color": target_color,
        "non_target_action": "pass",
        "trigger_line": 300,
        "flow_direction": 1,
        "control_conf": 0.45,
        "min_hits": 2,
        "track_iou": 0.30,
        "track_max_age": 12,
        "startup_delay": 2.0,
        "infer_interval_ms": 40,
        "servo": {
            "enabled": True,
            "period_ns": 5_000_000,
            "min_duty_ns": 1_100_000,
            "max_duty_ns": 1_900_000,
            "init_duty_ns": 1_500_000,
            "reset_duty_ns": 1_500_000,
            "target_duty_ns": 1_630_000,
            "other_duty_ns": 1_370_000,
            "hold_seconds": 2.0,
            "smooth_steps": 15,
            "smooth_delay": 0.01,
            "queue_size": 20,
        },
    }


def default_config() -> dict[str, Any]:
    return {
        "system": {
            "name": "K1 多层视觉分拣系统",
            "model_path": "models/my_yolov11m/model/best_yolov11n_int8_fix.q.onnx",
            "labels_path": "models/my_yolov11m/data/label.txt",
            "camera_width": 640,
            "camera_height": 480,
            "camera_fps": 30,
            "camera_cache_size": 2,
            "conf_threshold": 0.15,
            "nms_iou": 0.45,
            "topk": 100,
            "warmup_runs": 10,
            "camera_scan_max_index": 64,
            "jpeg_quality": 92,
        },
        "layers": [
            default_layer("layer_1", "第一层", "red"),
            default_layer("layer_2", "第二层", "yellow"),
            default_layer("layer_3", "第三层", "blue"),
            default_layer("layer_4", "第四层", "green"),
        ],
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _resolve_path(value: str | None, base_dir: Path) -> str | None:
    if not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve())


def validate_config(config: dict[str, Any]) -> None:
    layer_ids: set[str] = set()
    for layer in config.get("layers", []):
        layer_id = str(layer.get("id", "")).strip()
        if not layer_id:
            raise ValueError("每一层都必须有 id")
        if layer_id in layer_ids:
            raise ValueError(f"层 ID 重复: {layer_id}")
        layer_ids.add(layer_id)

        color = str(layer.get("target_color", "")).lower()
        if color not in SUPPORTED_COLORS:
            raise ValueError(
                f"{layer_id} 的 target_color 必须是 {', '.join(SUPPORTED_COLORS)}"
            )

        action = str(layer.get("non_target_action", "pass")).lower()
        if action not in SUPPORTED_NON_TARGET_ACTIONS:
            raise ValueError(
                f"{layer_id} 的 non_target_action 必须是 pass 或 other"
            )

        if int(layer.get("flow_direction", 1)) not in (-1, 1):
            raise ValueError(f"{layer_id} 的 flow_direction 只能是 -1 或 1")

        servo = layer.get("servo", {})
        period = int(servo.get("period_ns", 0))
        min_duty = int(servo.get("min_duty_ns", 0))
        max_duty = int(servo.get("max_duty_ns", 0))
        if period <= 0 or not (0 <= min_duty < max_duty <= period):
            raise ValueError(f"{layer_id} 的 PWM 安全范围不正确")
        for key in (
            "init_duty_ns",
            "reset_duty_ns",
            "target_duty_ns",
            "other_duty_ns",
        ):
            duty = int(servo.get(key, 0))
            if not (min_duty <= duty <= max_duty):
                raise ValueError(f"{layer_id} 的 {key}={duty} 超出安全范围")


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    config_path = Path(path).resolve()
    base = default_config()
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        config = _deep_merge(base, loaded)
    else:
        config = base

    project_dir = config_path.parent
    system = config.setdefault("system", {})
    system["model_path"] = _resolve_path(system.get("model_path"), project_dir)
    system["labels_path"] = _resolve_path(system.get("labels_path"), project_dir)

    validate_config(config)
    return config


def save_config(path: str | os.PathLike[str], config: dict[str, Any]) -> None:
    validate_config(config)
    config_path = Path(path).resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    serializable = copy.deepcopy(config)
    project_dir = config_path.parent
    system = serializable.get("system", {})
    for key in ("model_path", "labels_path"):
        value = system.get(key)
        if value:
            try:
                system[key] = str(Path(value).resolve().relative_to(project_dir))
            except ValueError:
                system[key] = str(Path(value).resolve())

    fd, temp_name = tempfile.mkstemp(
        prefix=config_path.name + ".",
        suffix=".tmp",
        dir=str(config_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            yaml.safe_dump(
                serializable,
                file,
                allow_unicode=True,
                sort_keys=False,
            )
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, config_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
