#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from sorter.system import SorterSystem


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DEFAULT_CONFIG = BASE_DIR / "config.yaml"

system_manager: SorterSystem | None = None


def manager() -> SorterSystem:
    if system_manager is None:
        raise HTTPException(status_code=503, detail="系统尚未初始化")
    return system_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global system_manager
    config_path = os.environ.get("SORTER_CONFIG", str(DEFAULT_CONFIG))
    system_manager = SorterSystem(config_path)
    try:
        yield
    finally:
        if system_manager is not None:
            system_manager.close()
        system_manager = None


app = FastAPI(
    title="K1 多层视觉分拣系统",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))



@app.get("/console")
def console() -> FileResponse:
    return FileResponse(str(WEB_DIR / "console.html"))


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return manager().status()


@app.get("/api/devices")
def api_devices() -> dict[str, Any]:
    return manager().device_snapshot()


@app.post("/api/devices/rescan")
def api_rescan_devices(
    payload: dict[str, Any] = Body(default={}),
) -> dict[str, Any]:
    try:
        return manager().rescan_devices(
            probe_cameras=bool(payload.get("probe_cameras", True))
        )
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/layers")
def api_layers() -> list[dict[str, Any]]:
    return manager().status()["layers"]


@app.put("/api/layers/{layer_id}/config")
def api_update_layer(
    layer_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    try:
        return manager().update_layer(layer_id, payload)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/target-color")
def api_target_color(
    layer_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    try:
        color = str(payload.get("target_color", ""))
        reset_counts = bool(payload.get("reset_counts", True))
        return manager().set_target_color(layer_id, color, reset_counts)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/start")
def api_start_layer(layer_id: str) -> dict[str, Any]:
    try:
        return manager().start_layer(layer_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/pause")
def api_pause_layer(layer_id: str) -> dict[str, Any]:
    try:
        return manager().pause_layer(layer_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/resume")
def api_resume_layer(layer_id: str) -> dict[str, Any]:
    try:
        return manager().resume_layer(layer_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/stop")
def api_stop_layer(layer_id: str) -> dict[str, Any]:
    try:
        return manager().stop_layer(layer_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/reset-counts")
def api_reset_layer_counts(layer_id: str) -> dict[str, Any]:
    try:
        return manager().reset_layer_counts(layer_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/layers/{layer_id}/manual/{action}")
def api_manual_action(layer_id: str, action: str) -> dict[str, Any]:
    try:
        return manager().manual_action(layer_id, action)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/system/start")
def api_start_all() -> dict[str, Any]:
    return manager().start_all()


@app.post("/api/system/pause")
def api_pause_all() -> dict[str, Any]:
    return manager().pause_all()


@app.post("/api/system/stop")
def api_stop_all() -> dict[str, Any]:
    return manager().stop_all()


@app.post("/api/system/reset-counts")
def api_reset_all_counts() -> dict[str, Any]:
    return manager().reset_all_counts()


@app.get("/api/logs")
def api_logs(limit: int = 100) -> list[dict[str, Any]]:
    return manager().recent_logs(limit)


@app.get("/api/layers/{layer_id}/stream")
def api_layer_stream(layer_id: str) -> StreamingResponse:
    try:
        layer = manager().get_layer(layer_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    def generate():
        last_frame: bytes | None = None
        while True:
            frame = layer.latest_frame_bytes()
            if frame and frame != last_frame:
                last_frame = frame
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
            time.sleep(0.05)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(manager().status())
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="K1 多层视觉分拣 Web 服务")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    os.environ["SORTER_CONFIG"] = str(Path(args.config).resolve())
    uvicorn.run(
        "app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

# --- K1_DIRECT_PWM_MANUAL_SERVO_START ---
# 运行中手动控制舵机补丁：
# 直接从 config.yaml 读取 layer 的 pwm_chip / pwm_channel / duty 参数，
# 绕过原来的“运行中禁止手动控制”限制，直接写 /sys/class/pwm。

import json as _k1_pwm_json
import re as _k1_pwm_re
import time as _k1_pwm_time
from pathlib import Path as _K1PWMPath
from fastapi.responses import JSONResponse as _K1PWMJSONResponse

try:
    import yaml as _k1_pwm_yaml
except Exception:
    _k1_pwm_yaml = None

_K1_PWM_BASE_DIR = _K1PWMPath(__file__).resolve().parent
_K1_PWM_CONFIG = _K1_PWM_BASE_DIR / "config.yaml"

def _k1_pwm_load_config():
    if _k1_pwm_yaml is None:
        raise RuntimeError("PyYAML 未安装，无法读取 config.yaml")
    with open(_K1_PWM_CONFIG, "r", encoding="utf-8") as f:
        data = _k1_pwm_yaml.safe_load(f) or {}
    return data

def _k1_pwm_layer_index(layer_id):
    m = _k1_pwm_re.search(r"layer_(\d+)", str(layer_id))
    if not m:
        return None
    return int(m.group(1)) - 1

def _k1_pwm_find_layer(cfg, layer_id):
    layers = cfg.get("layers")

    if isinstance(layers, dict):
        if layer_id in layers:
            item = layers[layer_id]
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("id", layer_id)
                return item

        for k, v in layers.items():
            if not isinstance(v, dict):
                continue
            if v.get("id") == layer_id or v.get("layer_id") == layer_id:
                return v

    if isinstance(layers, list):
        for item in layers:
            if not isinstance(item, dict):
                continue
            if item.get("id") == layer_id or item.get("layer_id") == layer_id:
                return item

        idx = _k1_pwm_layer_index(layer_id)
        if idx is not None and 0 <= idx < len(layers):
            item = layers[idx]
            if isinstance(item, dict):
                return item

    # 兜底递归搜索
    def walk(obj):
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    for d in walk(cfg):
        if d.get("id") == layer_id or d.get("layer_id") == layer_id:
            return d

    return None

def _k1_pwm_deep_get(obj, keys, default=None):
    if isinstance(keys, str):
        keys = [keys]

    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return obj[k]
        for v in obj.values():
            r = _k1_pwm_deep_get(v, keys, None)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _k1_pwm_deep_get(v, keys, None)
            if r is not None:
                return r

    return default

def _k1_pwm_normalize_chip(chip):
    chip = str(chip or "").strip()
    if not chip:
        return ""
    if chip.startswith("/sys/class/pwm/pwmchip"):
        return chip
    if chip.startswith("pwmchip"):
        return "/sys/class/pwm/" + chip
    return chip

def _k1_pwm_get_layer_pwm(layer, action):
    chip = _k1_pwm_deep_get(layer, ["pwm_chip", "chip_path", "chip"], "")
    channel = _k1_pwm_deep_get(layer, ["pwm_channel", "channel"], 0)

    chip = _k1_pwm_normalize_chip(chip)

    try:
        channel = int(channel)
    except Exception:
        channel = 0

    period = _k1_pwm_deep_get(layer, ["period_ns", "period"], 5000000)

    if action == "target":
        duty = _k1_pwm_deep_get(layer, ["target_duty_ns", "target_duty"], 1630000)
    elif action == "other":
        duty = _k1_pwm_deep_get(layer, ["other_duty_ns", "other_duty"], 1370000)
    else:
        duty = _k1_pwm_deep_get(layer, ["reset_duty_ns", "init_duty_ns", "reset_duty", "init_duty"], 1500000)

    try:
        period = int(period)
    except Exception:
        period = 5000000

    try:
        duty = int(duty)
    except Exception:
        duty = 1500000

    return chip, channel, period, duty

def _k1_pwm_write(path, value):
    path = _K1PWMPath(path)
    path.write_text(str(value), encoding="utf-8")

def _k1_pwm_export(chip, channel):
    chip_path = _K1PWMPath(chip)
    pwm_path = chip_path / f"pwm{channel}"

    if pwm_path.exists():
        return pwm_path

    export_path = chip_path / "export"
    if export_path.exists():
        try:
            export_path.write_text(str(channel), encoding="utf-8")
        except Exception:
            pass

    for _ in range(20):
        if pwm_path.exists():
            return pwm_path
        _k1_pwm_time.sleep(0.05)

    return pwm_path

def _k1_pwm_direct_write(chip, channel, period, duty):
    chip_path = _K1PWMPath(chip)

    if not chip_path.exists():
        raise RuntimeError(f"PWM chip 不存在：{chip}")

    pwm_path = _k1_pwm_export(chip, channel)

    if not pwm_path.exists():
        raise RuntimeError(f"PWM 通道不存在：{pwm_path}")

    period_path = pwm_path / "period"
    duty_path = pwm_path / "duty_cycle"
    enable_path = pwm_path / "enable"
    polarity_path = pwm_path / "polarity"

    # 避免 duty 大于 period
    if duty >= period:
        duty = max(0, period - 1)

    # 尽量设置极性
    try:
        if polarity_path.exists():
            polarity_path.write_text("normal", encoding="utf-8")
    except Exception:
        pass

    # 某些内核 enable=1 时不能改 period，所以先尝试关一下
    try:
        if enable_path.exists():
            enable_path.write_text("0", encoding="utf-8")
    except Exception:
        pass

    try:
        if period_path.exists():
            period_path.write_text(str(period), encoding="utf-8")
    except Exception:
        pass

    if duty_path.exists():
        duty_path.write_text(str(duty), encoding="utf-8")
    else:
        raise RuntimeError(f"找不到 duty_cycle：{duty_path}")

    if enable_path.exists():
        enable_path.write_text("1", encoding="utf-8")

    return {
        "chip": chip,
        "channel": channel,
        "period_ns": period,
        "duty_ns": duty,
        "pwm_path": str(pwm_path),
    }

def _k1_pwm_parse_action_from_request(path, body_bytes):
    low = str(path).lower()
    body_text = ""

    try:
        body_text = body_bytes.decode("utf-8", errors="ignore").lower()
    except Exception:
        body_text = ""

    action = None

    joined = low + " " + body_text

    if "target" in joined or "目标" in joined:
        action = "target"
    elif "other" in joined:
        action = "other"
    elif "reset" in joined or "home" in joined or "neutral" in joined or "复位" in joined:
        action = "reset"

    return action

async def _k1_pwm_rebuild_request(request, body):
    async def receive():
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }
    request._receive = receive
    return request

@app.middleware("http")
async def _k1_direct_pwm_manual_servo_middleware(request, call_next):
    path = request.url.path
    method = request.method.upper()

    m = _k1_pwm_re.search(r"/api/layers/(layer_\d+)", path.lower())

    if method == "POST" and m and any(k in path.lower() for k in ("servo", "manual", "target", "other", "reset")):
        body = await request.body()
        action = _k1_pwm_parse_action_from_request(path, body)

        if action is None:
            request = await _k1_pwm_rebuild_request(request, body)
            return await call_next(request)

        layer_id = m.group(1)

        try:
            cfg = _k1_pwm_load_config()
            layer = _k1_pwm_find_layer(cfg, layer_id)

            if layer is None:
                return _K1PWMJSONResponse(
                    {
                        "ok": False,
                        "detail": f"config.yaml 里未找到层：{layer_id}",
                        "layer_id": layer_id,
                        "action": action,
                    },
                    status_code=400,
                )

            chip, channel, period, duty = _k1_pwm_get_layer_pwm(layer, action)

            if not chip:
                return _K1PWMJSONResponse(
                    {
                        "ok": False,
                        "detail": f"{layer_id} 没有保存 pwm_chip，请在网页选择 PWM 通道后点击保存参数",
                        "layer_id": layer_id,
                        "action": action,
                        "layer": layer,
                    },
                    status_code=400,
                )

            result = _k1_pwm_direct_write(chip, channel, period, duty)

            try:
                with open("/tmp/k1_manual_pwm.log", "a", encoding="utf-8") as f:
                    f.write(f"{_k1_pwm_time.time()} {layer_id} {action} {result}\n")
            except Exception:
                pass

            return _K1PWMJSONResponse(
                {
                    "ok": True,
                    "running_allowed": True,
                    "mode": "direct_sysfs_pwm",
                    "layer_id": layer_id,
                    "action": action,
                    "result": result,
                }
            )

        except Exception as e:
            return _K1PWMJSONResponse(
                {
                    "ok": False,
                    "running_allowed": True,
                    "mode": "direct_sysfs_pwm",
                    "layer_id": layer_id,
                    "action": action,
                    "detail": str(e),
                },
                status_code=500,
            )

    return await call_next(request)

# --- K1_DIRECT_PWM_MANUAL_SERVO_END ---

