from __future__ import annotations

import glob
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

import cv2


def _numeric_video_sort(path: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", path)
    return (int(match.group(1)) if match else 10**9, path)


def _read_text(path: str, default: str = "") -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return default


def _stable_uid(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _camera_identity(sys_class: str, name: str, device_realpath: str) -> tuple[str, dict[str, str]]:
    metadata: dict[str, str] = {}
    current = Path(device_realpath)
    for parent in (current, *current.parents):
        for key in ("serial", "idVendor", "idProduct", "manufacturer", "product"):
            if key in metadata:
                continue
            value = _read_text(str(parent / key), "")
            if value:
                metadata[key] = value
        if "serial" in metadata and "idVendor" in metadata and "idProduct" in metadata:
            break

    interface_index = _read_text(f"{sys_class}/index", "0")
    metadata["interface_index"] = interface_index
    if metadata.get("serial"):
        identity = "|".join(
            [
                metadata.get("idVendor", ""),
                metadata.get("idProduct", ""),
                metadata["serial"],
                interface_index,
            ]
        )
    else:
        identity = "|".join([name, device_realpath, interface_index])
    return identity, metadata


class DeviceScanner:
    """扫描可采集视频节点和 Linux PWM 通道。"""

    def __init__(self, camera_scan_max_index: int = 64):
        self.camera_scan_max_index = max(0, int(camera_scan_max_index))

    def scan_cameras(
        self,
        probe: bool = True,
        skip_paths: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        skip_paths = {str(Path(path)) for path in (skip_paths or set())}
        candidates = sorted(glob.glob("/dev/video*"), key=_numeric_video_sort)
        devices: list[dict[str, Any]] = []

        for path in candidates:
            match = re.search(r"(\d+)$", path)
            if match and int(match.group(1)) > self.camera_scan_max_index:
                continue

            basename = os.path.basename(path)
            sys_class = f"/sys/class/video4linux/{basename}"
            name = _read_text(f"{sys_class}/name", basename)
            device_realpath = os.path.realpath(f"{sys_class}/device")
            identity, metadata = _camera_identity(sys_class, name, device_realpath)
            uid = _stable_uid("camera", identity)

            item: dict[str, Any] = {
                "uid": uid,
                "path": path,
                "name": name,
                "device_path": device_realpath,
                "metadata": metadata,
                "online": os.path.exists(path),
                "capture_ok": False,
                "busy": False,
                "width": None,
                "height": None,
                "fps": None,
                "backend": None,
            }

            if path in skip_paths:
                item["capture_ok"] = True
                item["busy"] = True
                devices.append(item)
                continue

            if probe:
                capture = cv2.VideoCapture(path, cv2.CAP_V4L2)
                if not capture.isOpened():
                    capture.release()
                    capture = cv2.VideoCapture(path)

                if capture.isOpened():
                    item["backend"] = capture.getBackendName()
                    item["width"] = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                    item["height"] = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                    item["fps"] = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)

                    ok = False
                    for _ in range(3):
                        ok, frame = capture.read()
                        if ok and frame is not None:
                            item["capture_ok"] = True
                            item["width"] = int(frame.shape[1])
                            item["height"] = int(frame.shape[0])
                            break
                        time.sleep(0.03)

                capture.release()

            devices.append(item)

        return devices

    def scan_pwm(self) -> list[dict[str, Any]]:
        channels: list[dict[str, Any]] = []
        for chip_path in sorted(glob.glob("/sys/class/pwm/pwmchip*")):
            npwm_text = _read_text(os.path.join(chip_path, "npwm"), "0")
            try:
                npwm = int(npwm_text)
            except ValueError:
                npwm = 0

            device_realpath = os.path.realpath(os.path.join(chip_path, "device"))
            chip_name = os.path.basename(chip_path)

            for channel in range(max(0, npwm)):
                pwm_path = os.path.join(chip_path, f"pwm{channel}")
                uid = _stable_uid("pwm", device_realpath, chip_name, str(channel))
                channels.append(
                    {
                        "uid": uid,
                        "chip": chip_path,
                        "chip_name": chip_name,
                        "channel": channel,
                        "npwm": npwm,
                        "device_path": device_realpath,
                        "exported": os.path.exists(pwm_path),
                        "writable": (
                            os.access(os.path.join(pwm_path, "duty_cycle"), os.W_OK)
                            if os.path.exists(pwm_path)
                            else os.access(os.path.join(chip_path, "export"), os.W_OK)
                        ),
                    }
                )

        return channels

    def scan_all(
        self,
        probe_cameras: bool = True,
        skip_camera_paths: set[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "cameras": self.scan_cameras(
                probe=probe_cameras,
                skip_paths=skip_camera_paths,
            ),
            "pwm_channels": self.scan_pwm(),
        }

# --- K1_USB_CAMERA_UID_PATCH_START ---
# 快速修复：同型号 USB 摄像头 UID 撞车。
# 不调用 v4l2-ctl，避免后端启动卡住。
# 对可读摄像头使用 /dev/videoX + sysfs realpath 生成唯一 UID。

import hashlib as _k1_fast_uid_hashlib
from pathlib import Path as _K1FastUidPath
import inspect as _k1_fast_uid_inspect

def _k1_fast_uid_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def _k1_fast_uid_set(obj, key, value):
    if isinstance(obj, dict):
        obj[key] = value
    else:
        try:
            setattr(obj, key, value)
        except Exception:
            pass
    return obj

def _k1_fast_uid_realpath(video_path):
    try:
        name = _K1FastUidPath(str(video_path)).name
        return str((_K1FastUidPath("/sys/class/video4linux") / name / "device").resolve())
    except Exception:
        return str(video_path)

def _k1_fast_uid_fix_camera(cam):
    path = str(_k1_fast_uid_get(cam, "path", ""))
    capture_ok = bool(_k1_fast_uid_get(cam, "capture_ok", False))

    if not path.startswith("/dev/video"):
        return cam

    if not capture_ok:
        return cam

    real = _k1_fast_uid_realpath(path)

    # 用真实 sysfs 路径 + /dev/videoX 区分 /dev/video20 和 /dev/video22
    raw = f"{real}|{path}"
    new_uid = "camera-" + _k1_fast_uid_hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    _k1_fast_uid_set(cam, "uid", new_uid)
    _k1_fast_uid_set(cam, "uid_source", "sysfs_realpath_plus_video_path")

    meta = _k1_fast_uid_get(cam, "metadata", None)
    if isinstance(meta, dict):
        meta["uid_source"] = "sysfs_realpath_plus_video_path"
        meta["sysfs_realpath"] = real

    return cam

def _k1_fast_uid_fix_result(result):
    if isinstance(result, list):
        for cam in result:
            _k1_fast_uid_fix_camera(cam)
        return result

    if isinstance(result, dict):
        cams = result.get("cameras")
        if isinstance(cams, list):
            for cam in cams:
                _k1_fast_uid_fix_camera(cam)
        return result

    if hasattr(result, "cameras"):
        try:
            for cam in result.cameras:
                _k1_fast_uid_fix_camera(cam)
        except Exception:
            pass
        return result

    return result

def _k1_fast_uid_wrap(fn):
    if getattr(fn, "_k1_fast_uid_wrapped", False):
        return fn

    if _k1_fast_uid_inspect.iscoroutinefunction(fn):
        async def awrapped(*args, **kwargs):
            result = await fn(*args, **kwargs)
            return _k1_fast_uid_fix_result(result)
        awrapped._k1_fast_uid_wrapped = True
        return awrapped

    def wrapped(*args, **kwargs):
        result = fn(*args, **kwargs)
        return _k1_fast_uid_fix_result(result)

    wrapped._k1_fast_uid_wrapped = True
    return wrapped

# 包裹常见扫描函数
for _name in (
    "scan_cameras",
    "list_cameras",
    "discover_cameras",
    "scan_video_devices",
    "scan_devices",
    "rescan",
):
    _fn = globals().get(_name)
    if callable(_fn):
        globals()[_name] = _k1_fast_uid_wrap(_fn)

# 包裹扫描类中的常见方法
for _cls_name, _cls in list(globals().items()):
    if not _k1_fast_uid_inspect.isclass(_cls):
        continue

    for _method_name, _method in list(vars(_cls).items()):
        if not _k1_fast_uid_inspect.isfunction(_method):
            continue

        if _method_name in (
            "scan_cameras",
            "list_cameras",
            "discover_cameras",
            "scan_video_devices",
            "scan_devices",
            "rescan",
            "refresh",
        ):
            setattr(_cls, _method_name, _k1_fast_uid_wrap(_method))

# --- K1_USB_CAMERA_UID_PATCH_END ---

