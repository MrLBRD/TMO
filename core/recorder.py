from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
import queue
import threading
import time

import cv2
import numpy as np

try:
    from pyzbar.pyzbar import decode as zbar_decode
    from pyzbar.pyzbar import ZBarSymbol
except Exception:
    zbar_decode = None
    ZBarSymbol = None

from .storage import build_video_path, default_output_dir, ensure_dir, is_valid_order_id, sanitize_order_id


@dataclass(frozen=True)
class RecorderEvent:
    type: str
    order_id: str | None = None
    message: str | None = None
    timestamp: float = field(default_factory=time.time)


def list_cameras(max_index: int = 10) -> list[tuple[int, int | None, int | None]]:
    found: list[tuple[int, int | None, int | None]] = []
    prev_log_level: int | None = None
    used_log_api: str | None = None
    try:
        log_api = getattr(getattr(cv2, "utils", None), "logging", None)
        if log_api is not None and hasattr(log_api, "setLogLevel"):
            if hasattr(log_api, "getLogLevel"):
                prev_log_level = int(log_api.getLogLevel())
            silent = int(getattr(log_api, "LOG_LEVEL_SILENT", 0))
            log_api.setLogLevel(silent)
            used_log_api = "utils"
        elif hasattr(cv2, "setLogLevel"):
            if hasattr(cv2, "getLogLevel"):
                prev_log_level = int(cv2.getLogLevel())
            cv2.setLogLevel(0)
            used_log_api = "cv2"
    except Exception:
        prev_log_level = None
        used_log_api = None

    try:
        for idx in range(max_index + 1):
            cap: cv2.VideoCapture | None
            if os.name == "nt":
                cap = None
                for api in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                    probe = cv2.VideoCapture(idx, api)
                    if probe.isOpened():
                        cap = probe
                        break
                    try:
                        probe.release()
                    except Exception:
                        pass
                if cap is None:
                    probe = cv2.VideoCapture(idx)
                    if probe.isOpened():
                        cap = probe
                    else:
                        try:
                            probe.release()
                        except Exception:
                            pass
                        continue
            else:
                cap = cv2.VideoCapture(idx)
                if not cap.isOpened():
                    try:
                        cap.release()
                    except Exception:
                        pass
                    continue

            width: int | None = None
            height: int | None = None
            try:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                if w > 0 and h > 0:
                    width, height = w, h
                else:
                    ok, frame = cap.read()
                    if ok and frame is not None:
                        fh, fw = frame.shape[:2]
                        width, height = int(fw), int(fh)
            except Exception:
                pass
            finally:
                try:
                    cap.release()
                except Exception:
                    pass

            found.append((idx, width, height))
    finally:
        if prev_log_level is not None:
            try:
                if used_log_api == "utils":
                    cv2.utils.logging.setLogLevel(prev_log_level)
                elif used_log_api == "cv2":
                    cv2.setLogLevel(prev_log_level)
            except Exception:
                pass

    return found


class Recorder:
    def __init__(
        self,
        camera_index: int = 0,
        camera_flip: str = "none",
        output_dir: Path | None = None,
    ) -> None:
        self.camera_index = camera_index
        self.camera_flip = str(camera_flip or "none").strip().lower()
        self.output_dir = output_dir or default_output_dir()

        self.events: queue.Queue[RecorderEvent] = queue.Queue()

        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._capture: cv2.VideoCapture | None = None

        self._latest_frame_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None

        self._fps: float = 30.0
        self._frame_size: tuple[int, int] | None = None

        self._recording_lock = threading.Lock()
        self._recording_order_id: str | None = None
        self._recording_path: Path | None = None
        self._recording_started_at: float | None = None
        self._writer_queue: queue.Queue[tuple[np.ndarray, float] | None] | None = None
        self._writer_thread: threading.Thread | None = None
        self._writer_control: dict[str, int | bool] | None = None

        self.scan_roi_ratio = 0.75
        self.scan_cooldown_seconds = 1.0
        self.writer_queue_size = 120

        self.qr_debug_cooldown_seconds = 0.3
        self._last_qr_debug_value: str | None = None
        self._last_qr_debug_time = 0.0

        self._last_scan_value: str | None = None
        self._last_scan_time = 0.0
        self._opencv_qr_detector: cv2.QRCodeDetector | None = None
        try:
            self._opencv_qr_detector = cv2.QRCodeDetector()
        except Exception:
            self._opencv_qr_detector = None

        # Frame skipping for QR scanning (performance optimization)
        self._qr_frame_counter = 0
        self._qr_scan_interval = 2  # Scan every 2nd frame (~15fps at 30fps camera)

        if zbar_decode is not None:
            self._qr_backend: str | None = "pyzbar"
        elif self._opencv_qr_detector is not None:
            self._qr_backend = "opencv"
        else:
            self._qr_backend = None

        self._qr_available = self._qr_backend is not None

    @property
    def qr_available(self) -> bool:
        return self._qr_available

    @property
    def qr_backend(self) -> str | None:
        return self._qr_backend

    @property
    def is_recording(self) -> bool:
        with self._recording_lock:
            return self._recording_order_id is not None

    @property
    def recording_order_id(self) -> str | None:
        with self._recording_lock:
            return self._recording_order_id

    def get_latest_frame(self) -> np.ndarray | None:
        with self._latest_frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def start(self) -> None:
        if self._capture_thread and self._capture_thread.is_alive():
            return

        self._stop_event.clear()

        if os.name == "nt":
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_MSMF)
            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                cap = cv2.VideoCapture(self.camera_index)
        else:
            cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.events.put(RecorderEvent(type="error", message="camera_open_failed"))
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps and fps > 1:
            self._fps = float(fps)
        else:
            self._fps = 30.0

        self._capture = cap
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="tmo_capture",
            daemon=True,
        )
        self._capture_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        if self._capture_thread is not None:
            self._capture_thread.join(timeout=2)

        self.stop_recording(wait=True)

        if self._capture is not None:
            self._capture.release()

        self._capture_thread = None
        self._capture = None

    def stop_recording(self, wait: bool = False, drop_tail: bool = False) -> None:
        with self._recording_lock:
            order_id = self._recording_order_id
            path = self._recording_path
            q = self._writer_queue
            t = self._writer_thread
            control = self._writer_control

            self._recording_order_id = None
            self._recording_path = None
            self._recording_started_at = None
            self._writer_queue = None
            self._writer_thread = None
            self._writer_control = None

        if control is not None:
            try:
                control["drop_tail"] = bool(drop_tail)
            except Exception:
                pass

        if q is not None:
            self._enqueue_sentinel(q)

        if wait and t is not None:
            t.join(timeout=5)

        if order_id:
            self.events.put(
                RecorderEvent(
                    type="recording_stopped",
                    order_id=order_id,
                    message=str(path) if path else None,
                )
            )

    def start_recording(self, order_id: str) -> None:
        safe_id = sanitize_order_id(order_id)

        frame_size = self._frame_size
        if frame_size is None:
            self.events.put(RecorderEvent(type="error", message="frame_size_unknown"))
            return

        path = build_video_path(safe_id, output_dir=self.output_dir)
        ensure_dir(path.parent)

        width, height = frame_size
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, self._fps, (width, height))
        if not writer.isOpened():
            self.events.put(RecorderEvent(type="error", message="video_writer_open_failed"))
            return

        tail_buffer_frames = max(1, int(round(self._fps * 1.0)))
        control: dict[str, int | bool] = {
            "drop_tail": False,
            "tail_buffer_frames": int(tail_buffer_frames),
        }

        q: queue.Queue[tuple[np.ndarray, float] | None] = queue.Queue(maxsize=self.writer_queue_size)
        t = threading.Thread(
            target=self._writer_loop,
            args=(writer, q, control),
            name="tmo_writer",
            daemon=True,
        )

        with self._recording_lock:
            self._recording_order_id = safe_id
            self._recording_path = path
            self._recording_started_at = time.time()
            self._writer_queue = q
            self._writer_thread = t
            self._writer_control = control

        t.start()
        self._beep()

        self.events.put(
            RecorderEvent(type="recording_started", order_id=safe_id, message=str(path))
        )

    def _capture_loop(self) -> None:
        cap = self._capture
        if cap is None:
            return

        while not self._stop_event.is_set():
            ok, frame = cap.read()
            if not ok:
                self.events.put(RecorderEvent(type="error", message="camera_read_failed"))
                time.sleep(0.2)
                continue

            try:
                frame = self._apply_camera_flip(frame)
            except Exception:
                pass

            height, width = frame.shape[:2]
            self._frame_size = (width, height)

            display_frame = frame.copy()
            display_frame = self._draw_scan_roi(display_frame)
            if self.is_recording:
                display_frame = self._draw_rec_indicator(display_frame)

            with self._latest_frame_lock:
                self._latest_frame = display_frame

            self._enqueue_recording_frame(frame)

            # QR scanning with frame skipping for performance
            self._qr_frame_counter += 1
            if self._qr_frame_counter >= self._qr_scan_interval:
                self._qr_frame_counter = 0
                self._scan_and_handle(frame)

    def _apply_camera_flip(self, frame: np.ndarray) -> np.ndarray:
        mode = (self.camera_flip or "none").strip().lower()
        if mode in ("none", "0", "off", "false", "no"):
            return frame
        if mode in ("h", "horizontal", "x", "mirror"):
            return cv2.flip(frame, 1)
        if mode in ("v", "vertical", "y"):
            return cv2.flip(frame, 0)
        if mode in ("hv", "vh", "both", "xy", "180"):
            return cv2.flip(frame, -1)
        return frame

    def _emit_qr_debug(self, raw: str, order_id: str | None) -> None:
        raw = str(raw).strip()
        if not raw:
            return

        now = time.time()
        if (
            raw == self._last_qr_debug_value
            and (now - self._last_qr_debug_time) < self.qr_debug_cooldown_seconds
        ):
            return

        self._last_qr_debug_value = raw
        self._last_qr_debug_time = now
        self.events.put(RecorderEvent(type="qr_detected", order_id=order_id, message=raw))

    def _enqueue_recording_frame(self, frame: np.ndarray) -> None:
        with self._recording_lock:
            q = self._writer_queue

        if q is None:
            return

        payload = (frame, time.time())
        try:
            q.put_nowait(payload)
        except queue.Full:
            try:
                _ = q.get_nowait()
            except queue.Empty:
                return
            try:
                q.put_nowait(payload)
            except queue.Full:
                return

    def _scan_and_handle(self, frame: np.ndarray) -> None:
        if not self._qr_available:
            return

        roi = self._extract_scan_roi(frame)

        if self._qr_backend == "pyzbar" and zbar_decode is not None:
            try:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            except Exception:
                return

            try:
                if ZBarSymbol is not None:
                    results = zbar_decode(gray, symbols=[ZBarSymbol.QRCODE])
                else:
                    results = zbar_decode(gray)
            except Exception:
                if self._opencv_qr_detector is not None:
                    self._qr_backend = "opencv"
                else:
                    self._qr_available = False
                self.events.put(RecorderEvent(type="error", message="qr_decoder_failed"))
                return

            now = time.time()
            for res in results:
                if getattr(res, "type", "") != "QRCODE":
                    continue

                raw = getattr(res, "data", b"")
                try:
                    data = raw.decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue

                order_id = self._extract_order_id_from_qr_value(data)
                self._emit_qr_debug(data, order_id)
                if order_id is None:
                    continue

                if order_id == self._last_scan_value and (now - self._last_scan_time) < self.scan_cooldown_seconds:
                    continue

                self._last_scan_value = order_id
                self._last_scan_time = now

                self._handle_order_id(order_id)
                return

        if self._qr_backend == "opencv":
            detector = self._opencv_qr_detector
            if detector is None:
                self._qr_available = False
                return

            candidates: list[str] = []
            try:
                if hasattr(detector, "detectAndDecodeMulti"):
                    ok, decoded_info, _points, _ = detector.detectAndDecodeMulti(roi)
                    if ok and decoded_info:
                        candidates = [s for s in decoded_info if s]
                else:
                    data, _points, _ = detector.detectAndDecode(roi)
                    if data:
                        candidates = [data]
            except Exception:
                self._qr_available = False
                self.events.put(RecorderEvent(type="error", message="qr_opencv_failed"))
                return

            now = time.time()
            for data in candidates:
                data = str(data).strip()

                order_id = self._extract_order_id_from_qr_value(data)
                self._emit_qr_debug(data, order_id)
                if order_id is None:
                    continue

                if order_id == self._last_scan_value and (now - self._last_scan_time) < self.scan_cooldown_seconds:
                    continue

                self._last_scan_value = order_id
                self._last_scan_time = now

                self._handle_order_id(order_id)
                return

    def _extract_order_id_from_qr_value(self, value: str) -> str | None:
        value = str(value).strip()
        if not value:
            return None

        prefix = "tk-"
        if not value.lower().startswith(prefix):
            return None

        candidate = value[len(prefix) :].strip()

        candidate = sanitize_order_id(candidate)
        if not is_valid_order_id(candidate):
            return None

        return candidate

    def _handle_order_id(self, order_id: str) -> None:
        safe_id = sanitize_order_id(order_id)
        if not is_valid_order_id(safe_id):
            return

        with self._recording_lock:
            current = self._recording_order_id

        if current == safe_id:
            return

        if current is not None:
            self.stop_recording(wait=False, drop_tail=True)

        self.start_recording(safe_id)

    def _scan_roi_bounds(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        h, w = frame.shape[:2]
        roi_w = int(w * self.scan_roi_ratio)
        roi_h = int(h * self.scan_roi_ratio)
        x1 = max(0, (w - roi_w) // 2)
        y1 = max(0, (h - roi_h) // 2)
        x2 = min(w, x1 + roi_w)
        y2 = min(h, y1 + roi_h)
        return x1, y1, x2, y2

    def _extract_scan_roi(self, frame: np.ndarray) -> np.ndarray:
        x1, y1, x2, y2 = self._scan_roi_bounds(frame)
        return frame[y1:y2, x1:x2]

    def _draw_scan_roi(self, frame: np.ndarray) -> np.ndarray:
        x1, y1, x2, y2 = self._scan_roi_bounds(frame)
        h, w = frame.shape[:2]

        thickness = max(2, int(min(w, h) * 0.004))
        color = (0, 255, 0) if self._qr_available else (160, 160, 160)

        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
        alpha = 0.10 if self._qr_available else 0.06
        frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        return frame

    def _draw_rec_indicator(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        m = max(10, int(min(w, h) * 0.015))
        r = max(8, int(min(w, h) * 0.02))
        cx = m + r
        cy = m + r

        with self._recording_lock:
            order_id = self._recording_order_id
            started_at = self._recording_started_at

        elapsed = int(time.time() - started_at) if started_at else 0
        timer = f"{elapsed // 60:02d}:{elapsed % 60:02d}"

        lines: list[str] = [f"REC {timer}"]
        if order_id:
            lines.append(order_id)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.65, min(w, h) / 900)
        thickness = max(2, int(font_scale * 2))
        pad = max(6, int(font_scale * 10))
        gap = max(6, int(font_scale * 10))

        sizes = [cv2.getTextSize(t, font, font_scale, thickness) for t in lines]
        text_w = max(s[0][0] for s in sizes)
        text_h_total = sum(s[0][1] for s in sizes) + gap * (len(lines) - 1)

        text_x = cx + r + m
        box_x1 = max(0, text_x - pad)
        box_y1 = max(0, m - pad)
        box_x2 = min(w - 1, box_x1 + text_w + pad * 2)
        box_y2 = min(h - 1, box_y1 + text_h_total + pad * 2)

        overlay = frame.copy()
        cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.45, frame, 0.55, 0)
        cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 255), 2)

        cv2.circle(frame, (cx, cy), r, (0, 0, 255), -1)

        y = box_y1 + pad
        for i, t in enumerate(lines):
            (tw, th), _baseline = cv2.getTextSize(t, font, font_scale, thickness)
            y += th
            color = (0, 0, 255) if i == 0 else (255, 255, 255)
            cv2.putText(
                frame,
                t,
                (box_x1 + pad, y),
                font,
                font_scale,
                color,
                thickness,
                cv2.LINE_AA,
            )
            y += gap

        return frame

    def _writer_loop(
        self,
        writer: cv2.VideoWriter,
        q: queue.Queue[tuple[np.ndarray, float] | None],
        control: dict[str, int | bool],
    ) -> None:
        try:
            tail_buffer_frames = int(control.get("tail_buffer_frames", 0) or 0)
        except Exception:
            tail_buffer_frames = 0
        if tail_buffer_frames < 0:
            tail_buffer_frames = 0

        buffer: deque[tuple[np.ndarray, float]] = deque()

        def _write_frame(frame: np.ndarray, frame_ts: float) -> None:
            try:
                try:
                    ts = datetime.fromtimestamp(float(frame_ts)).strftime("%Y-%m-%d %H:%M:%S")
                    h, w = frame.shape[:2]
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = max(0.55, min(w, h) / 1400)
                    thickness = max(1, int(font_scale * 2))
                    (tw, th), _baseline = cv2.getTextSize(ts, font, font_scale, thickness)
                    x = max(8, w - tw - 12)
                    y = max(th + 8, h - 12)
                    cv2.putText(
                        frame,
                        ts,
                        (x, y),
                        font,
                        font_scale,
                        (0, 0, 0),
                        thickness + 2,
                        cv2.LINE_AA,
                    )
                    cv2.putText(
                        frame,
                        ts,
                        (x, y),
                        font,
                        font_scale,
                        (255, 255, 255),
                        thickness,
                        cv2.LINE_AA,
                    )
                except Exception:
                    pass

                writer.write(frame)
            except Exception:
                return

        while True:
            item = q.get()
            if item is None:
                break
            try:
                frame, frame_ts = item
            except Exception:
                continue

            buffer.append((frame, frame_ts))
            while tail_buffer_frames > 0 and len(buffer) > tail_buffer_frames:
                f, ts = buffer.popleft()
                _write_frame(f, ts)

        drop_tail = False
        try:
            drop_tail = bool(control.get("drop_tail", False))
        except Exception:
            drop_tail = False

        if not drop_tail:
            while buffer:
                f, ts = buffer.popleft()
                _write_frame(f, ts)

        try:
            writer.release()
        except Exception:
            return

    def _enqueue_sentinel(self, q: queue.Queue[tuple[np.ndarray, float] | None]) -> None:
        while True:
            try:
                q.put_nowait(None)
                return
            except queue.Full:
                try:
                    _ = q.get_nowait()
                except queue.Empty:
                    return

    def _beep(self) -> None:
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            try:
                print("\a", end="", flush=True)
            except Exception:
                return
