from __future__ import annotations

import copy
import threading
import time
from typing import Any

import cv2

# --- K1_DIRECT_COLOR_TRIGGER_START ---
# 直接颜色触发模式：
# 取消触发线逻辑。识别到目标颜色后直接给舵机发送 target 信号；
# 识别到非目标颜色时，如果 non_target_action == "other"，直接发送 other 信号；
# 用冷却时间避免每一帧重复触发舵机。

import time as _k1_direct_time

def _k1_direct_get(obj, name, default=None):
    try:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)
    except Exception:
        return default

def _k1_direct_label_of(det):
    for k in ("label", "class_name", "name", "color"):
        v = _k1_direct_get(det, k, None)
        if v is not None:
            return str(v).lower()

    cls_id = _k1_direct_get(det, "class_id", None)
    if cls_id is None:
        cls_id = _k1_direct_get(det, "cls", None)

    return str(cls_id).lower() if cls_id is not None else ""

def _k1_direct_conf_of(det):
    for k in ("conf", "confidence", "score"):
        v = _k1_direct_get(det, k, None)
        if v is not None:
            try:
                return float(v)
            except Exception:
                return 0.0
    return 1.0

def _k1_direct_collect_detections(args, kwargs):
    candidates = []

    for v in args:
        if isinstance(v, (list, tuple)):
            candidates.extend(v)

    for k in ("detections", "tracks", "objects", "results"):
        v = kwargs.get(k)
        if isinstance(v, (list, tuple)):
            candidates.extend(v)

    return candidates

def _k1_direct_servo_action(gate, action):
    servo = _k1_direct_get(gate, "servo", None)
    if servo is None:
        servo = _k1_direct_get(gate, "_servo", None)

    if servo is None:
        layer = _k1_direct_get(gate, "layer", None)
        servo = _k1_direct_get(layer, "servo", None)

    if servo is None:
        return False

    names = {
        "target": ("target", "move_target", "to_target", "target_position", "trigger_target"),
        "other": ("other", "move_other", "to_other", "other_position", "trigger_other"),
    }.get(action, ())

    for name in names:
        fn = _k1_direct_get(servo, name, None)
        if callable(fn):
            try:
                fn()
                return True
            except TypeError:
                try:
                    fn(block=False)
                    return True
                except Exception:
                    pass
            except Exception:
                pass

    # 兼容通用 action / enqueue 接口
    for name in ("action", "do_action", "enqueue", "trigger", "move"):
        fn = _k1_direct_get(servo, name, None)
        if callable(fn):
            try:
                fn(action)
                return True
            except Exception:
                pass

    return False

def _k1_direct_increment(gate, action):
    if action == "target":
        for name in ("target_count", "target_total"):
            if hasattr(gate, name):
                try:
                    setattr(gate, name, int(getattr(gate, name)) + 1)
                    return
                except Exception:
                    pass

    if action == "other":
        for name in ("other_count", "other_total", "non_target_count"):
            if hasattr(gate, name):
                try:
                    setattr(gate, name, int(getattr(gate, name)) + 1)
                    return
                except Exception:
                    pass

def _k1_direct_trigger_update(gate, *args, **kwargs):
    now = _k1_direct_time.time()

    cooldown = _k1_direct_get(gate, "hold_seconds", None)
    if cooldown is None:
        cooldown = _k1_direct_get(gate, "cooldown_seconds", None)
    if cooldown is None:
        cooldown = _k1_direct_get(gate, "action_cooldown", None)
    if cooldown is None:
        cooldown = 1.0

    try:
        cooldown = float(cooldown)
    except Exception:
        cooldown = 1.0

    last_t = _k1_direct_get(gate, "_k1_direct_last_action_time", 0.0)
    if now - float(last_t or 0.0) < cooldown:
        return None

    target_color = str(_k1_direct_get(gate, "target_color", "")).lower()
    non_target_action = str(_k1_direct_get(gate, "non_target_action", "pass")).lower()
    control_conf = _k1_direct_get(gate, "control_conf", None)

    if control_conf is None:
        control_conf = _k1_direct_get(gate, "min_conf", None)
    if control_conf is None:
        control_conf = 0.0

    try:
        control_conf = float(control_conf)
    except Exception:
        control_conf = 0.0

    detections = _k1_direct_collect_detections(args, kwargs)

    has_target = False
    has_other = False

    for det in detections:
        label = _k1_direct_label_of(det)
        conf = _k1_direct_conf_of(det)

        if conf < control_conf:
            continue

        if not label:
            continue

        if target_color and target_color in label:
            has_target = True
            break

        # 只把四种颜色类当成非目标，避免把无关类别也打出去
        if any(c in label for c in ("red", "yellow", "blue", "green")):
            has_other = True

    if has_target:
        ok = _k1_direct_servo_action(gate, "target")
        if ok:
            setattr(gate, "_k1_direct_last_action_time", now)
            setattr(gate, "last_action", "TARGET")
            _k1_direct_increment(gate, "target")
        return "target"

    if has_other and non_target_action == "other":
        ok = _k1_direct_servo_action(gate, "other")
        if ok:
            setattr(gate, "_k1_direct_last_action_time", now)
            setattr(gate, "last_action", "OTHER")
            _k1_direct_increment(gate, "other")
        return "other"

    return None

# 给触发门类打补丁
for _cls_name in ("ColorTriggerGate", "TriggerGate", "SortGate"):
    _cls = globals().get(_cls_name)
    if _cls is not None:
        for _method_name in ("update", "process", "handle", "step", "check"):
            if hasattr(_cls, _method_name):
                setattr(_cls, _method_name, _k1_direct_trigger_update)

# 去掉触发线绘制
_K1_ORIG_CV2_LINE_FOR_TRIGGER = cv2.line

def _k1_no_trigger_line(img, pt1, pt2, color, thickness=1, *args, **kwargs):
    try:
        # 原触发线一般是横线，且 y1 == y2
        if isinstance(pt1, tuple) and isinstance(pt2, tuple):
            if len(pt1) >= 2 and len(pt2) >= 2 and pt1[1] == pt2[1]:
                # 跳过很长的横线，保留检测框线条
                if abs(pt2[0] - pt1[0]) > 200:
                    return img
    except Exception:
        pass

    return _K1_ORIG_CV2_LINE_FOR_TRIGGER(img, pt1, pt2, color, thickness, *args, **kwargs)

cv2.line = _k1_no_trigger_line

# --- K1_DIRECT_COLOR_TRIGGER_END ---

import numpy as np

from .config import SUPPORTED_COLORS, SUPPORTED_NON_TARGET_ACTIONS
from .logstore import LogStore
from .servo import ServoPWM
from .vision import (
    InferenceJob,
    InferenceScheduler,
    IoUTracker,
    LatestFrameCamera,
    color_for_class,
    draw_tracks,
)


class LayerController:
    """单层分拣控制器：摄像头、跟踪、触发逻辑和舵机均独立。"""

    VALID_STATES = ("DISCONNECTED", "IDLE", "RUNNING", "PAUSED", "FAULT")

    def __init__(
        self,
        config: dict[str, Any],
        system_config: dict[str, Any],
        labels: list[str],
        scheduler: InferenceScheduler,
        log_store: LogStore,
    ):
        self.config = copy.deepcopy(config)
        self.system_config = system_config
        self.labels = labels
        self.scheduler = scheduler
        self.log_store = log_store

        self.layer_id = str(config["id"])
        self.name = str(config.get("name", self.layer_id))
        self.lock = threading.RLock()
        self.state = "IDLE"
        self.last_error: str | None = None
        self.camera: LatestFrameCamera | None = None
        self.servo: ServoPWM | None = None
        self.capture_thread: threading.Thread | None = None
        self.capture_running = False
        self.inference_pending = False
        self.last_submit_time = 0.0
        self.last_result_time = 0.0
        self.last_frame_time = 0.0
        self.fps = 0.0
        self.inference_ms = 0.0
        self.processed_frames = 0
        self.dropped_jobs = 0

        self.tracker = IoUTracker(
            iou_threshold=float(config.get("track_iou", 0.30)),
            max_age=int(config.get("track_max_age", 12)),
        )
        self.track_state: dict[int, dict[str, Any]] = {}
        self.target_count = 0
        self.other_count = 0
        self.total_crossings = 0
        self.last_action = "NONE"
        self.started_at: float | None = None
        self.active_after = 0.0

        self.latest_jpeg: bytes | None = None
        self.latest_frame_shape: tuple[int, int] | None = None
        self._update_placeholder("未启动")

    def _log(self, level: str, message: str, details: dict[str, Any] | None = None) -> None:
        writer = getattr(self.log_store, level.lower(), self.log_store.info)
        writer(self.layer_id, message, details)

    def _camera_source(self) -> str | int:
        path = self.config.get("camera_path")
        if not path:
            raise RuntimeError("未绑定摄像头")
        if isinstance(path, int):
            return path
        text = str(path)
        if text.startswith("/dev/video"):
            suffix = text.removeprefix("/dev/video")
            if suffix.isdigit():
                return int(suffix)
        return text

    def _build_servo(self) -> ServoPWM | None:
        servo_cfg = self.config.get("servo", {})
        if not bool(servo_cfg.get("enabled", True)):
            return None
        pwm_chip = self.config.get("pwm_chip")
        pwm_channel = self.config.get("pwm_channel")
        if pwm_chip is None or pwm_channel is None:
            raise RuntimeError("未绑定 PWM 通道")

        return ServoPWM(
            pwm_chip=str(pwm_chip),
            pwm_channel=int(pwm_channel),
            period_ns=int(servo_cfg["period_ns"]),
            min_duty_ns=int(servo_cfg["min_duty_ns"]),
            max_duty_ns=int(servo_cfg["max_duty_ns"]),
            init_duty_ns=int(servo_cfg["init_duty_ns"]),
            reset_duty_ns=int(servo_cfg["reset_duty_ns"]),
            target_duty_ns=int(servo_cfg["target_duty_ns"]),
            other_duty_ns=int(servo_cfg["other_duty_ns"]),
            hold_seconds=float(servo_cfg["hold_seconds"]),
            smooth_steps=int(servo_cfg["smooth_steps"]),
            smooth_delay=float(servo_cfg["smooth_delay"]),
            queue_size=int(servo_cfg.get("queue_size", 20)),
        )

    def start(self) -> None:
        with self.lock:
            if self.state == "RUNNING":
                return
            if not bool(self.config.get("enabled", True)):
                raise RuntimeError("该层已禁用")
            if self.camera is None:
                self.camera = LatestFrameCamera(
                    source=self._camera_source(),
                    width=int(self.system_config.get("camera_width", 640)),
                    height=int(self.system_config.get("camera_height", 480)),
                    fps=int(self.system_config.get("camera_fps", 30)),
                    cache_size=int(self.system_config.get("camera_cache_size", 2)),
                )
            if self.servo is None and bool(self.config.get("servo", {}).get("enabled", True)):
                self.servo = self._build_servo()

            self.state = "RUNNING"
            self.last_error = None
            self.capture_running = True
            self.started_at = self.started_at or time.time()
            self.active_after = time.time() + max(
                0.0, float(self.config.get("startup_delay", 2.0))
            )
            if self.capture_thread is None or not self.capture_thread.is_alive():
                self.capture_thread = threading.Thread(
                    target=self._capture_loop,
                    daemon=True,
                    name=f"capture-{self.layer_id}",
                )
                self.capture_thread.start()
            self._log("info", "分拣层已启动")

    def pause(self) -> None:
        with self.lock:
            if self.state == "RUNNING":
                self.state = "PAUSED"
                self._log("info", "分拣层已暂停")

    def resume(self) -> None:
        with self.lock:
            if self.state == "PAUSED":
                self.state = "RUNNING"
                self.active_after = time.time() + 0.5
                self._log("info", "分拣层已继续")

    def stop(self) -> None:
        with self.lock:
            self.capture_running = False
            self.state = "IDLE"
            self.inference_pending = False

        if self.capture_thread is not None:
            self.capture_thread.join(timeout=1.5)
            self.capture_thread = None

        with self.lock:
            if self.camera is not None:
                self.camera.close()
                self.camera = None
            if self.servo is not None:
                self.servo.close(reset=False)
                self.servo = None
            self.tracker.reset()
            self.track_state.clear()
            self._update_placeholder("已停止")
            self._log("info", "分拣层已停止")

    def close(self) -> None:
        self.stop()

    def _capture_loop(self) -> None:
        while self.capture_running:
            with self.lock:
                state = self.state
                camera = self.camera
                pending = self.inference_pending
                interval = max(0.0, float(self.config.get("infer_interval_ms", 40)) / 1000.0)

            if state == "PAUSED":
                time.sleep(0.05)
                continue
            if state != "RUNNING" or camera is None:
                time.sleep(0.02)
                continue

            frame = camera.read_latest()
            if frame is None:
                if camera.last_frame_time and time.time() - camera.last_frame_time > 3.0:
                    with self.lock:
                        self.last_error = "摄像头超过 3 秒没有新画面"
                time.sleep(0.005)
                continue

            self.last_frame_time = time.time()
            now = time.monotonic()
            if pending or now - self.last_submit_time < interval:
                time.sleep(0.001)
                continue

            job = InferenceJob(
                layer_id=self.layer_id,
                frame=frame,
                conf_threshold=float(self.system_config.get("conf_threshold", 0.15)),
                iou_threshold=float(self.system_config.get("nms_iou", 0.45)),
                topk=int(self.system_config.get("topk", 100)),
                callback=self._on_inference,
            )
            accepted = self.scheduler.submit(job)
            with self.lock:
                if accepted:
                    self.inference_pending = True
                    self.last_submit_time = now
                else:
                    self.dropped_jobs += 1
            if not accepted:
                time.sleep(0.005)

    def _on_inference(
        self,
        frame: np.ndarray,
        detections: list[dict[str, Any]] | None,
        inference_ms: float,
        error: Exception | None,
    ) -> None:
        with self.lock:
            self.inference_pending = False
            current_state = self.state
            if current_state not in ("RUNNING", "PAUSED"):
                return

        if error is not None:
            with self.lock:
                self.last_error = str(error)
                self.state = "FAULT"
            self._log("error", "模型推理失败", {"error": str(error)})
            self._update_placeholder("推理故障")
            return

        assert detections is not None
        tracked = self.tracker.update(detections)
        if current_state == "RUNNING":
            self._handle_crossings(tracked)

        annotated = frame.copy()
        draw_tracks(annotated, tracked, self.labels)
        self._draw_overlay(annotated)

        quality = int(self.system_config.get("jpeg_quality", 80))
        ok, encoded = cv2.imencode(
            ".jpg",
            annotated,
            [cv2.IMWRITE_JPEG_QUALITY, max(40, min(95, quality))],
        )

        now = time.time()
        with self.lock:
            if self.last_result_time > 0:
                instantaneous = 1.0 / max(1e-6, now - self.last_result_time)
                self.fps = instantaneous if self.fps <= 0 else self.fps * 0.8 + instantaneous * 0.2
            self.last_result_time = now
            self.inference_ms = float(inference_ms)
            self.processed_frames += 1
            self.last_error = None
            self.latest_frame_shape = (annotated.shape[1], annotated.shape[0])
            if ok:
                self.latest_jpeg = encoded.tobytes()

    def _handle_crossings(self, detections: list[dict[str, Any]]) -> None:
        now = time.time()
        if now < self.active_after:
            return

        with self.lock:
            target_color = str(self.config.get("target_color", "red")).lower()
            control_conf = float(self.config.get("control_conf", 0.45))
            min_hits = int(self.config.get("min_hits", 2))
            trigger_line = int(self.config.get("trigger_line", 300))
            flow_direction = int(self.config.get("flow_direction", 1))
            non_target_action = str(self.config.get("non_target_action", "pass"))
            servo = self.servo

        for det in detections:
            class_id = int(det["class_id"])
            if not (0 <= class_id < len(self.labels)):
                continue
            name = self.labels[class_id].strip().lower()
            score = float(det["score"])
            hits = int(det.get("hits", 1))
            track_id = int(det["track_id"])
            x, y, w, h = [float(value) for value in det["box"]]
            center_y = y + h * 0.5

            state = self.track_state.get(
                track_id,
                {"prev_y": None, "triggered": False, "last_seen": now},
            )
            prev_y = state["prev_y"]
            if flow_direction > 0:
                crossed = prev_y is not None and prev_y < trigger_line <= center_y
            else:
                crossed = prev_y is not None and prev_y > trigger_line >= center_y

            if (
                crossed
                and not state["triggered"]
                and score >= control_conf
                and hits >= min_hits
            ):
                is_target = name == target_color
                accepted = True
                action_text = "PASS"

                if is_target:
                    action_text = "TARGET"
                    if servo is not None:
                        accepted = servo.enqueue(ServoPWM.ACTION_TARGET, name, track_id)
                else:
                    if non_target_action == "other":
                        action_text = "OTHER"
                        if servo is not None:
                            accepted = servo.enqueue(ServoPWM.ACTION_OTHER, name, track_id)
                    else:
                        action_text = "PASS"

                if accepted:
                    state["triggered"] = True
                    with self.lock:
                        self.total_crossings += 1
                        if is_target:
                            self.target_count += 1
                        else:
                            self.other_count += 1
                        self.last_action = f"{action_text}:{name.upper()}"

                    self._log(
                        "info",
                        f"检测到 {name.upper()}，执行 {action_text}",
                        {
                            "target_color": target_color,
                            "score": round(score, 4),
                            "track_id": track_id,
                            "action": action_text,
                        },
                    )
                else:
                    self._log("warning", "舵机命令队列已满，动作被丢弃")

            state["prev_y"] = center_y
            state["last_seen"] = now
            self.track_state[track_id] = state

        expired = [
            track_id
            for track_id, state in self.track_state.items()
            if now - float(state["last_seen"]) > 3.0
        ]
        for track_id in expired:
            del self.track_state[track_id]

    def _draw_overlay(self, frame: np.ndarray) -> None:
        with self.lock:
            target_color = str(self.config.get("target_color", "red"))
            trigger_line = int(self.config.get("trigger_line", 300))
            target_count = self.target_count
            other_count = self.other_count
            state = self.state
            fps = self.fps
            inference_ms = self.inference_ms
            last_action = self.last_action
            non_target_action = str(self.config.get("non_target_action", "pass"))

        height, width = frame.shape[:2]
        y = max(0, min(height - 1, trigger_line))
        color = color_for_class(target_color)
        cv2.line(frame, (0, y), (width, y), color, 3)
        lines = [
            f"{self.name} | TARGET:{target_color.upper()} | STATE:{state}",
            f"Target:{target_count} Other:{other_count} Mode:{non_target_action.upper()}",
            f"FPS:{fps:.1f} Infer:{inference_ms:.1f}ms Last:{last_action}",
        ]
        for index, text in enumerate(lines):
            cv2.putText(
                frame,
                text,
                (10, 28 + index * 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                color if index == 0 else (255, 255, 255),
                2,
            )
        cv2.putText(
            frame,
            f"TRIGGER Y={y}",
            (10, max(24, y - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            color,
            2,
        )

    def _update_placeholder(self, text: str) -> None:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            self.name,
            (30, 130),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255),
            2,
        )
        cv2.putText(
            frame,
            text,
            (30, 200),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (180, 180, 180),
            2,
        )
        ok, encoded = cv2.imencode(".jpg", frame)
        if ok:
            self.latest_jpeg = encoded.tobytes()

    def latest_frame_bytes(self) -> bytes:
        with self.lock:
            return self.latest_jpeg or b""

    def reset_counts(self) -> None:
        with self.lock:
            self.target_count = 0
            self.other_count = 0
            self.total_crossings = 0
            self.last_action = "NONE"
            self.track_state.clear()
            self.tracker.reset()
        self._log("info", "计数和追踪状态已清零")

    def set_target_color(self, color: str, reset_counts: bool = True) -> None:
        color = str(color).strip().lower()
        if color not in SUPPORTED_COLORS:
            raise ValueError(f"目标颜色必须是 {', '.join(SUPPORTED_COLORS)}")
        with self.lock:
            old = str(self.config.get("target_color", "red"))
            self.config["target_color"] = color
            self.track_state.clear()
            self.tracker.reset()
            if reset_counts:
                self.target_count = 0
                self.other_count = 0
                self.total_crossings = 0
                self.last_action = "NONE"
        self._log("info", f"目标颜色从 {old.upper()} 切换为 {color.upper()}")

    def update_config(self, updates: dict[str, Any]) -> None:
        updates = copy.deepcopy(updates)
        target_changed = False
        old_target = str(self.config.get("target_color", "red"))
        with self.lock:
            if self.state in ("RUNNING", "PAUSED") and any(
                key in updates
                for key in ("camera_uid", "camera_path", "pwm_uid", "pwm_chip", "pwm_channel")
            ):
                raise RuntimeError("运行或暂停状态下不能更换摄像头/PWM，请先停止该层")

            if "target_color" in updates:
                color = str(updates["target_color"]).lower()
                if color not in SUPPORTED_COLORS:
                    raise ValueError("不支持的目标颜色")
            if "non_target_action" in updates:
                action = str(updates["non_target_action"]).lower()
                if action not in SUPPORTED_NON_TARGET_ACTIONS:
                    raise ValueError("non_target_action 只能是 pass 或 other")

            servo_updates = updates.pop("servo", None)
            self.config.update(copy.deepcopy(updates))
            if servo_updates is not None:
                self.config.setdefault("servo", {}).update(copy.deepcopy(servo_updates))

            new_target = str(self.config.get("target_color", "red"))
            target_changed = new_target != old_target
            if target_changed:
                self.target_count = 0
                self.other_count = 0
                self.total_crossings = 0
                self.last_action = "NONE"

            self.name = str(self.config.get("name", self.layer_id))
            self.tracker.iou_threshold = float(self.config.get("track_iou", 0.30))
            self.tracker.max_age = int(self.config.get("track_max_age", 12))
            self.track_state.clear()
            self.tracker.reset()

        if target_changed:
            self._log(
                "info",
                f"目标颜色从 {old_target.upper()} 切换为 {new_target.upper()}，计数已清零",
            )
        else:
            self._log("info", "层参数已更新")

    def manual_action(self, action: str) -> None:
        with self.lock:
            if self.state == "RUNNING":
                raise RuntimeError("自动运行中不能手动控制舵机，请先暂停或停止")
            if self.servo is None:
                self.servo = self._build_servo()
            servo = self.servo

        if servo is None:
            raise RuntimeError("该层未启用舵机")
        if action not in (ServoPWM.ACTION_TARGET, ServoPWM.ACTION_OTHER, ServoPWM.ACTION_RESET):
            raise ValueError("未知手动动作")
        if not servo.enqueue(action, "manual", -1):
            raise RuntimeError("舵机命令队列已满")
        self._log("info", f"手动舵机动作: {action}")

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            runtime = time.time() - self.started_at if self.started_at else 0.0
            camera_status = self.camera.status() if self.camera is not None else None
            servo_status = self.servo.status() if self.servo is not None else None
            return {
                "id": self.layer_id,
                "name": self.name,
                "state": self.state,
                "enabled": bool(self.config.get("enabled", True)),
                "camera_uid": self.config.get("camera_uid"),
                "camera_path": self.config.get("camera_path"),
                "pwm_uid": self.config.get("pwm_uid"),
                "pwm_chip": self.config.get("pwm_chip"),
                "pwm_channel": self.config.get("pwm_channel"),
                "target_color": self.config.get("target_color"),
                "non_target_action": self.config.get("non_target_action", "pass"),
                "trigger_line": int(self.config.get("trigger_line", 300)),
                "control_conf": float(self.config.get("control_conf", 0.45)),
                "min_hits": int(self.config.get("min_hits", 2)),
                "target_count": self.target_count,
                "other_count": self.other_count,
                "total_crossings": self.total_crossings,
                "last_action": self.last_action,
                "fps": round(self.fps, 2),
                "inference_ms": round(self.inference_ms, 2),
                "processed_frames": self.processed_frames,
                "dropped_jobs": self.dropped_jobs,
                "runtime_seconds": round(runtime, 1),
                "last_error": self.last_error,
                "camera": camera_status,
                "servo": servo_status,
                "servo_config": copy.deepcopy(self.config.get("servo", {})),
            }
