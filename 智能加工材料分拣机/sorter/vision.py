from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

import cv2

# --- K1_FORCE_V4L2_CAPTURE_START ---
# 强制 USB 摄像头使用 V4L2 + MJPG + 640x480 + 小缓冲。
# 解决多路同型号 USB 摄像头有时打开但不持续出帧的问题。

import os as _k1_v4l2_os

if not globals().get("_K1_FORCE_V4L2_CAPTURE_INSTALLED", False):
    _K1_FORCE_V4L2_CAPTURE_INSTALLED = True
    _K1_ORIG_VIDEOCAPTURE = cv2.VideoCapture

    def _k1_is_video_source(src):
        s = str(src)
        return (
            isinstance(src, int)
            or s.isdigit()
            or s.startswith("/dev/video")
        )

    def _k1_forced_videocapture(src, apiPreference=None, *args, **kwargs):
        if _k1_is_video_source(src):
            if apiPreference is None:
                cap = _K1_ORIG_VIDEOCAPTURE(src, cv2.CAP_V4L2)
            else:
                cap = _K1_ORIG_VIDEOCAPTURE(src, apiPreference, *args, **kwargs)

            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 30)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            return cap

        if apiPreference is None:
            return _K1_ORIG_VIDEOCAPTURE(src)
        return _K1_ORIG_VIDEOCAPTURE(src, apiPreference, *args, **kwargs)

    cv2.VideoCapture = _k1_forced_videocapture

# --- K1_FORCE_V4L2_CAPTURE_END ---

import numpy as np
import onnxruntime as ort
import spacemit_ort  # noqa: F401  注册 SpaceMITExecutionProvider


class LatestFrameCamera:
    """独立线程采集摄像头，只保留最新帧。"""

    def __init__(
        self,
        source: str | int,
        width: int,
        height: int,
        fps: int,
        cache_size: int = 2,
    ):
        self.source = source
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.cache = deque(maxlen=max(1, int(cache_size)))
        self.lock = threading.Lock()
        self.running = True
        self.last_frame_time = 0.0
        self.read_failures = 0

        self.cap = self._open_capture(source)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f"无法打开摄像头 {source}")

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    @staticmethod
    def _open_capture(source: str | int) -> cv2.VideoCapture:
        capture = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(source)
        return capture

    def _capture_loop(self) -> None:
        while self.running:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.read_failures += 1
                time.sleep(0.01)
                continue

            self.last_frame_time = time.time()
            self.read_failures = 0
            with self.lock:
                self.cache.append(frame)

    def read_latest(self) -> np.ndarray | None:
        with self.lock:
            if not self.cache:
                return None
            frame = self.cache.pop()
            self.cache.clear()
            return frame

    def status(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "online": self.cap.isOpened(),
            "last_frame_time": self.last_frame_time,
            "read_failures": self.read_failures,
            "width": int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            "height": int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
            "fps": float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0),
        }

    def close(self) -> None:
        self.running = False
        try:
            self.cap.release()
        finally:
            self.thread.join(timeout=1.0)


class Preprocessor:
    def __init__(self, input_w: int, input_h: int):
        self.input_w = int(input_w)
        self.input_h = int(input_h)
        self.canvas = np.empty((self.input_h, self.input_w, 3), dtype=np.uint8)
        self.tensor = np.empty((1, 3, self.input_h, self.input_w), dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> tuple[np.ndarray, float, int, int]:
        src_h, src_w = frame.shape[:2]
        ratio = min(self.input_w / src_w, self.input_h / src_h)
        new_w = int(round(src_w * ratio))
        new_h = int(round(src_h * ratio))
        pad_x = (self.input_w - new_w) // 2
        pad_y = (self.input_h - new_h) // 2

        self.canvas.fill(114)
        if new_w == src_w and new_h == src_h:
            resized = frame
        else:
            resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        self.canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

        np.multiply(
            self.canvas[:, :, 2],
            1.0 / 255.0,
            out=self.tensor[0, 0],
            casting="unsafe",
        )
        np.multiply(
            self.canvas[:, :, 1],
            1.0 / 255.0,
            out=self.tensor[0, 1],
            casting="unsafe",
        )
        np.multiply(
            self.canvas[:, :, 0],
            1.0 / 255.0,
            out=self.tensor[0, 2],
            casting="unsafe",
        )

        return self.tensor, ratio, pad_x, pad_y


class IoUTracker:
    def __init__(self, iou_threshold: float = 0.30, max_age: int = 12):
        self.iou_threshold = float(iou_threshold)
        self.max_age = int(max_age)
        self.next_id = 1
        self.tracks: dict[int, dict[str, Any]] = {}

    @staticmethod
    def iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
        ax, ay, aw, ah = [float(value) for value in box_a]
        bx, by, bw, bh = [float(value) for value in box_b]
        aw, ah, bw, bh = max(0.0, aw), max(0.0, ah), max(0.0, bw), max(0.0, bh)
        ax2, ay2, bx2, by2 = ax + aw, ay + ah, bx + bw, by + bh
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        intersection = iw * ih
        union = aw * ah + bw * bh - intersection
        return 0.0 if union <= 1e-6 else intersection / union

    def reset(self) -> None:
        self.tracks.clear()
        self.next_id = 1

    def update(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[tuple[float, int, int]] = []

        for track_id, track in self.tracks.items():
            for det_index, det in enumerate(detections):
                if track["class_id"] != det["class_id"]:
                    continue
                overlap = self.iou(track["box"], det["box"])
                if overlap >= self.iou_threshold:
                    candidates.append((overlap, track_id, det_index))

        candidates.sort(key=lambda item: item[0], reverse=True)
        used_tracks: set[int] = set()
        used_detections: set[int] = set()

        for _, track_id, det_index in candidates:
            if track_id in used_tracks or det_index in used_detections:
                continue
            det = detections[det_index]
            track = self.tracks[track_id]
            track["box"] = det["box"].astype(np.float32).copy()
            track["score"] = float(det["score"])
            track["missed"] = 0
            track["hits"] += 1
            det["track_id"] = track_id
            det["hits"] = track["hits"]
            used_tracks.add(track_id)
            used_detections.add(det_index)

        for track_id in list(self.tracks):
            if track_id not in used_tracks:
                self.tracks[track_id]["missed"] += 1
                if self.tracks[track_id]["missed"] > self.max_age:
                    del self.tracks[track_id]

        for det_index, det in enumerate(detections):
            if det_index in used_detections:
                continue
            track_id = self.next_id
            self.next_id += 1
            self.tracks[track_id] = {
                "class_id": int(det["class_id"]),
                "box": det["box"].astype(np.float32).copy(),
                "score": float(det["score"]),
                "missed": 0,
                "hits": 1,
            }
            det["track_id"] = track_id
            det["hits"] = 1

        return detections


def nms_by_class(
    boxes: np.ndarray,
    scores: np.ndarray,
    class_ids: np.ndarray,
    iou_threshold: float,
) -> list[int]:
    kept: list[int] = []
    for class_id in np.unique(class_ids):
        local_ids = np.flatnonzero(class_ids == class_id)
        selected = cv2.dnn.NMSBoxes(
            boxes[local_ids].tolist(),
            scores[local_ids].astype(float).tolist(),
            score_threshold=0.0,
            nms_threshold=float(iou_threshold),
        )
        if selected is not None and len(selected) > 0:
            selected = np.asarray(selected).reshape(-1)
            kept.extend(local_ids[selected].tolist())
    return kept


def postprocess(
    output: list[np.ndarray],
    frame: np.ndarray,
    label_count: int,
    ratio: float,
    pad_x: int,
    pad_y: int,
    conf_threshold: float,
    iou_threshold: float,
    topk: int,
) -> list[dict[str, Any]]:
    pred = output[0]
    if pred.ndim == 3:
        pred = pred[0]
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T
    if pred.shape[1] < 4 + label_count:
        raise RuntimeError(f"模型输出维度异常: {pred.shape}")

    all_scores = pred[:, 4 : 4 + label_count]
    class_ids = np.argmax(all_scores, axis=1)
    scores = all_scores[np.arange(len(class_ids)), class_ids]
    selected_ids = np.flatnonzero(scores >= conf_threshold)
    if selected_ids.size == 0:
        return []

    if topk > 0 and selected_ids.size > topk:
        local_top = np.argpartition(scores[selected_ids], -topk)[-topk:]
        selected_ids = selected_ids[local_top]

    xywh = pred[selected_ids, :4]
    scores = scores[selected_ids]
    class_ids = class_ids[selected_ids]

    x1 = (xywh[:, 0] - 0.5 * xywh[:, 2] - pad_x) / ratio
    y1 = (xywh[:, 1] - 0.5 * xywh[:, 3] - pad_y) / ratio
    x2 = (xywh[:, 0] + 0.5 * xywh[:, 2] - pad_x) / ratio
    y2 = (xywh[:, 1] + 0.5 * xywh[:, 3] - pad_y) / ratio

    frame_h, frame_w = frame.shape[:2]
    x1 = np.clip(x1, 0, frame_w - 1).astype(np.int32)
    y1 = np.clip(y1, 0, frame_h - 1).astype(np.int32)
    x2 = np.clip(x2, 0, frame_w - 1).astype(np.int32)
    y2 = np.clip(y2, 0, frame_h - 1).astype(np.int32)

    boxes = np.stack((x1, y1, x2 - x1, y2 - y1), axis=1)
    valid = (boxes[:, 2] > 1) & (boxes[:, 3] > 1)
    boxes, scores, class_ids = boxes[valid], scores[valid], class_ids[valid]
    if len(boxes) == 0:
        return []

    kept = nms_by_class(boxes, scores, class_ids, iou_threshold)
    return [
        {
            "box": boxes[index].astype(np.float32),
            "score": float(scores[index]),
            "class_id": int(class_ids[index]),
        }
        for index in kept
    ]


def color_for_class(name: str) -> tuple[int, int, int]:
    return {
        "red": (0, 0, 255),
        "yellow": (0, 255, 255),
        "blue": (255, 0, 0),
        "green": (0, 255, 0),
    }.get(str(name).lower(), (255, 255, 255))


def draw_tracks(
    frame: np.ndarray,
    detections: list[dict[str, Any]],
    labels: list[str],
) -> None:
    for det in detections:
        x, y, w, h = [int(value) for value in det["box"]]
        class_id = int(det["class_id"])
        name = labels[class_id] if 0 <= class_id < len(labels) else str(class_id)
        color = color_for_class(name)
        track_id = int(det.get("track_id", -1))
        hits = int(det.get("hits", 1))
        score = float(det["score"])
        text = f"{name} ID:{track_id} H:{hits} {score:.2f}"

        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        center_x, center_y = int(x + w * 0.5), int(y + h * 0.5)
        cv2.circle(frame, (center_x, center_y), 4, color, -1)

        (text_w, text_h), baseline = cv2.getTextSize(
            text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2
        )
        text_y = max(text_h + 8, y)
        cv2.rectangle(
            frame,
            (x, text_y - text_h - 7),
            (x + text_w + 6, text_y + baseline - 2),
            color,
            -1,
        )
        cv2.putText(
            frame,
            text,
            (x + 3, text_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            2,
        )


class Detector:
    """共享的 YOLO ONNX Runtime 会话。"""

    def __init__(
        self,
        model_path: str,
        labels_path: str,
        warmup_runs: int = 10,
    ):
        self.labels = self._load_labels(labels_path)
        self.session = self._create_session(model_path)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        shape = self.session.get_inputs()[0].shape
        try:
            self.input_h = int(shape[2])
            self.input_w = int(shape[3])
        except Exception as error:
            raise RuntimeError(f"无法读取固定模型输入尺寸: {shape}") from error

        self.preprocessor = Preprocessor(self.input_w, self.input_h)
        if warmup_runs > 0:
            dummy = np.zeros((1, 3, self.input_h, self.input_w), dtype=np.float32)
            for _ in range(int(warmup_runs)):
                self.session.run([self.output_name], {self.input_name: dummy})

    @staticmethod
    def _load_labels(path: str) -> list[str]:
        with open(path, "r", encoding="utf-8") as file:
            labels = [line.strip() for line in file if line.strip()]
        if not labels:
            raise RuntimeError("标签文件为空")
        return labels

    @staticmethod
    def _create_session(model_path: str) -> ort.InferenceSession:
        available = ort.get_available_providers()
        if "SpaceMITExecutionProvider" not in available:
            raise RuntimeError(
                "SpaceMITExecutionProvider 不可用，请确认 spacemit_ort 已正确安装"
            )
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = [
            (
                "SpaceMITExecutionProvider",
                {"SPACEMIT_EP_INTRA_THREAD_NUM": "4"},
            ),
            "CPUExecutionProvider",
        ]
        return ort.InferenceSession(
            model_path,
            sess_options=options,
            providers=providers,
        )

    def infer(
        self,
        frame: np.ndarray,
        conf_threshold: float,
        iou_threshold: float,
        topk: int,
    ) -> tuple[list[dict[str, Any]], float]:
        start = time.perf_counter()
        tensor, ratio, pad_x, pad_y = self.preprocessor(frame)
        output = self.session.run([self.output_name], {self.input_name: tensor})
        detections = postprocess(
            output=output,
            frame=frame,
            label_count=len(self.labels),
            ratio=ratio,
            pad_x=pad_x,
            pad_y=pad_y,
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            topk=topk,
        )
        inference_ms = (time.perf_counter() - start) * 1000.0
        return detections, inference_ms


@dataclass
class InferenceJob:
    layer_id: str
    frame: np.ndarray
    conf_threshold: float
    iou_threshold: float
    topk: int
    callback: Callable[[np.ndarray, list[dict[str, Any]] | None, float, Exception | None], None]


class InferenceScheduler:
    """所有层共享一个推理线程，避免多个摄像头同时争抢 NPU。"""

    def __init__(self, detector: Detector, queue_size: int = 16):
        self.detector = detector
        self.jobs: queue.Queue[InferenceJob | None] = queue.Queue(maxsize=max(1, queue_size))
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def submit(self, job: InferenceJob) -> bool:
        try:
            self.jobs.put_nowait(job)
            return True
        except queue.Full:
            return False

    def _worker(self) -> None:
        while self.running:
            job = self.jobs.get()
            try:
                if job is None:
                    break
                try:
                    detections, inference_ms = self.detector.infer(
                        job.frame,
                        job.conf_threshold,
                        job.iou_threshold,
                        job.topk,
                    )
                    job.callback(job.frame, detections, inference_ms, None)
                except Exception as error:
                    job.callback(job.frame, None, 0.0, error)
            finally:
                self.jobs.task_done()

    def close(self) -> None:
        self.running = False
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        self.thread.join(timeout=2.0)
