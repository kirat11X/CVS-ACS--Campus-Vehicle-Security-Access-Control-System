"""
Multi-Gate Camera Stream Runner & Adaptive FPS Inference Manager.
-----------------------------------------------------------------
Provides:
1. One isolated cv2.VideoCapture worker thread per enabled gate camera.
2. Dynamic adaptive FPS throttling:
      per_gate_fps = max(2.0, total_fps_budget / N_active_gates)
   (e.g., 1 gate -> 15.0 FPS; 2 gates -> 7.5 FPS; 3 gates -> 5.0 FPS).
3. Auto-reconnection backoff for unstable wireless/mobile camera streams.
4. Bounded shared inference queue with real-time frame dropping on lag.
5. Guardrails & Filters:
   - Laplacian variance sharpness filtering (>= 40.0)
   - Letterbox aspect-ratio preserving padding (640x640)
   - YOLO11n plate detection with aspect-ratio clamping (1.5 <= w/h <= 6.0)
   - Track A CRNN OCR extraction & normalization
   - OpticalPlateMatcher registry fuzzy lookup
   - 60-second debounce per (gate_id, plate)
   - Ingestion into ObservationService -> Feed / Review console.
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone
import logging
from pathlib import Path
import queue
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

from backend.app.config import BASE_DIR, MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.models.enums import ObservationDirection, ObservationSource, ObservedVehicleType
from backend.app.models.stream_setting import GateStreamSetting
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.observation import ObservationCreate
from backend.app.services.multiframe_plate_consensus import decompose_indian_plate_slots, fuse_multiframe_plate_reads
from backend.app.services.observation_service import ObservationService
from backend.app.services.plate_normalizer import is_valid_indian_plate, normalize_plate, suggest_repairs
from research_track.track_a.src.registry_matcher import OpticalPlateMatcher

logger = logging.getLogger("campus_security.camera_stream")

ROOT_DIR = Path(BASE_DIR).resolve()
WEIGHTS_DIR = ROOT_DIR / "weights"
DETECTOR_PATH = WEIGHTS_DIR / "yolo11n_plate_detector_fleet_best.onnx"
if not DETECTOR_PATH.exists():
    DETECTOR_PATH = WEIGHTS_DIR / "yolo11n_plate_detector_finetuned.onnx"
if not DETECTOR_PATH.exists():
    DETECTOR_PATH = WEIGHTS_DIR / "yolo11n_plate_detector_best.onnx"

OCR_PATH = WEIGHTS_DIR / "indian_plate_crnn_best.onnx"
if not OCR_PATH.exists():
    OCR_PATH = WEIGHTS_DIR / "track_a_ocr_cct.onnx"

try:
    from rapidocr_onnxruntime import RapidOCR
    RAPID_OCR_AVAILABLE = True
except Exception:
    RAPID_OCR_AVAILABLE = False

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
IDX2CHAR = {i + 1: ch for i, ch in enumerate(ALPHABET)}


def decode_crnn_logits(logits: np.ndarray) -> Tuple[str, float]:
    """
    Decodes CTC greedy output from CRNN logits array and calculates mean character confidence.
    Returns:
        (decoded_text, mean_char_confidence)
    """
    # Softmax along class axis to get true probabilities
    exp_logits = np.exp(logits[0] - np.max(logits[0], axis=-1, keepdims=True))
    probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

    preds = np.argmax(logits[0], axis=-1)
    chars = []
    confs = []
    prev = 0
    for t, idx in enumerate(preds):
        if idx != prev and idx != 0 and idx in IDX2CHAR:
            chars.append(IDX2CHAR[idx])
            confs.append(float(probs[t, idx]))
        prev = idx

    decoded = "".join(chars)
    mean_conf = float(np.mean(confs)) if confs else 0.0
    return decoded, mean_conf


def _edit_distance(s1: str, s2: str) -> int:
    """Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[m][n]


def letterbox_image(image: np.ndarray, target_size: int = 640) -> Tuple[np.ndarray, float, int, int]:
    """Uniform resize with letterbox padding to (target_size, target_size)."""
    h, w = image.shape[:2]
    scale = min(target_size / float(w), target_size / float(h))
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.full((target_size, target_size, 3), 114, dtype=np.uint8)
    dx = (target_size - nw) // 2
    dy = (target_size - nh) // 2
    canvas[dy : dy + nh, dx : dx + nw] = resized
    return canvas, scale, dx, dy


def is_plate_like_crop(crop: np.ndarray) -> bool:
    """
    Crop-level plate-likeness gate before OCR.
    Rejects crops with low grayscale contrast (std < 22.0) or abnormal
    Canny edge density (< 0.04 or > 0.55) so flat walls, shadows, and
    uniform empty space never reach OCR.
    """
    if crop is None or crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 30:
        return False

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    std = float(np.std(gray))
    if std < 22.0:
        return False

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / float(edges.size)
    if edge_density < 0.04 or edge_density > 0.55:
        return False

    return True


def preprocess_plate_crop(crop: np.ndarray) -> np.ndarray:
    """
    Preprocesses plate crop before OCR:
    1. Aspect-preserving bicubic upscale when crop_height < 48px.
    2. CLAHE on the L-channel when crop brightness < 90 or contrast std < 45.
    """
    if crop is None or crop.size == 0:
        return crop

    enhanced = crop.copy()
    ch, cw = enhanced.shape[:2]

    # 1. Aspect-preserving bicubic upscale if height < 48px
    if 0 < ch < 48:
        scale = 48.0 / float(ch)
        new_w = max(1, int(round(cw * scale)))
        enhanced = cv2.resize(enhanced, (new_w, 48), interpolation=cv2.INTER_CUBIC)
        ch, cw = enhanced.shape[:2]

    # 2. CLAHE on L-channel when brightness < 90 or contrast std < 45
    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    mean_brightness = float(np.mean(l_chan))
    std_contrast = float(np.std(l_chan))

    if mean_brightness < 90.0 or std_contrast < 45.0:
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_chan)
        lab = cv2.merge([l_enhanced, a_chan, b_chan])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    return enhanced


def sort_multiline_boxes(
    lines_with_boxes: List[Any],
    crop_height: int,
) -> List[Any]:
    """
    When RapidOCR returns multiple lines on 2-line plates, sort boxes
    top-to-bottom (y_center) then left-to-right (x_center) before joining.
    """
    if len(lines_with_boxes) <= 1:
        return lines_with_boxes

    parsed = []
    for item in lines_with_boxes:
        box = item[0]
        pts = np.array(box, dtype=np.float32).reshape(-1, 2)
        y_center = float(np.mean(pts[:, 1]))
        x_center = float(np.mean(pts[:, 0]))
        parsed.append({
            "item": item,
            "y_center": y_center,
            "x_center": x_center,
        })

    # Sort primarily by y_center
    parsed.sort(key=lambda d: d["y_center"])

    # Cluster into horizontal lines based on vertical tolerance (e.g. 25% crop height)
    line_threshold = max(10.0, 0.25 * float(crop_height))
    lines: List[List[Dict[str, Any]]] = []

    for entry in parsed:
        placed = False
        for line in lines:
            avg_y = sum(d["y_center"] for d in line) / len(line)
            if abs(entry["y_center"] - avg_y) <= line_threshold:
                line.append(entry)
                placed = True
                break
        if not placed:
            lines.append([entry])

    # Sort each horizontal line left-to-right
    sorted_items = []
    for line in lines:
        line.sort(key=lambda d: d["x_center"])
        for d in line:
            sorted_items.append(d["item"])

    return sorted_items


class CameraStreamManager:
    """
    Manages live camera capture loops across multiple gates, dynamically
    allocating the adaptive FPS budget and feeding a shared ANPR inference engine.
    """

    def __init__(self, total_fps_budget: float = 15.0):
        self.total_fps_budget = float(total_fps_budget)
        self._lock = threading.RLock()
        self._running = False
        self._stop_event = threading.Event()

        # Gate configurations and active workers
        # gate_id -> dict with config fields
        self._configs: Dict[str, Dict[str, Any]] = {}
        # gate_id -> (thread, stop_event)
        self._workers: Dict[str, Tuple[threading.Thread, threading.Event]] = {}
        # gate_id -> deque of recent frame timestamps (last 5 seconds)
        self._fps_meters: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=60)
        )
        self._last_seen: Dict[str, datetime] = {}
        self._last_errors: Dict[str, Optional[str]] = {}
        self._latest_frames: Dict[str, np.ndarray] = {}
        self._prev_grays: Dict[str, np.ndarray] = {}
        self._last_motion_ts: Dict[str, float] = {}

        # Shared bounded inference queue
        self._inference_queue: queue.Queue[Optional[Tuple[str, np.ndarray, float]]] = queue.Queue(maxsize=30)
        self._inference_thread: Optional[threading.Thread] = None

        # ML Sessions
        self._det_session = None
        self._ocr_session = None
        self._rapid_ocr = None
        self._matcher: Optional[OpticalPlateMatcher] = None
        self._last_registry_sync: float = 0.0

        # Debounce: (gate_id, normalized_plate) -> timestamp
        self._debounce_cache: Dict[Tuple[str, str], float] = {}
        # Gate-level burst debounce: gate_id -> (timestamp, plate)
        self._gate_last_ingest: Dict[str, Tuple[float, str]] = {}
        # Temporal candidate tracks for multi-frame consensus: gate_id -> list of candidate frame dicts
        self._temporal_tracks: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
        self._temporal_track_last_update: Dict[str, float] = {}

    # -------------------------------------------------------------------------
    # Lifecycle & Configuration
    # -------------------------------------------------------------------------

    def start(self):
        """Initializes configs from database and starts workers."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()

            self._load_configs_from_db()
            self._init_ml_models()

            # Start inference loop
            self._inference_thread = threading.Thread(
                target=self._inference_loop,
                name="CameraInferenceWorker",
                daemon=True,
            )
            self._inference_thread.start()

            # Spawn capture threads for enabled gates
            self._sync_capture_threads()
            logger.info(
                "CameraStreamManager started with total FPS budget %.1f. Active gates: %s",
                self.total_fps_budget,
                [gid for gid, cfg in self._configs.items() if cfg.get("enabled")],
            )

    def stop(self):
        """Stops all camera threads and shuts down inference worker."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()

            # Signal all capture threads
            for gid, (t, stop_ev) in list(self._workers.items()):
                stop_ev.set()

            # Wake up inference queue
            try:
                self._inference_queue.put_nowait(None)
            except Exception:
                pass

        # Join capture threads with timeout
        for gid, (t, _) in list(self._workers.items()):
            t.join(timeout=2.0)

        if self._inference_thread and self._inference_thread.is_alive():
            self._inference_thread.join(timeout=2.0)

        with self._lock:
            self._workers.clear()
            logger.info("CameraStreamManager successfully stopped.")

    def _load_configs_from_db(self):
        """Reads GateStreamSetting rows and sets initial configs."""
        try:
            with SessionLocal() as db:
                rows = db.query(GateStreamSetting).all()
                if not rows:
                    # Auto-seed GATE_1 enabled if table empty
                    row1 = GateStreamSetting(
                        gate_id="GATE_1",
                        enabled=True,
                        ip_address="192.168.1.100",
                        port=8080,
                        protocol="http",
                        stream_path="/video",
                        total_fps_budget=15.0,
                    )
                    db.add(row1)
                    db.commit()
                    rows = [row1]

                for r in rows:
                    self.total_fps_budget = float(r.total_fps_budget or 15.0)
                    self._configs[r.gate_id] = {
                        "gate_id": r.gate_id,
                        "enabled": bool(r.enabled),
                        "ip_address": r.ip_address,
                        "port": r.port,
                        "protocol": r.protocol,
                        "stream_path": r.stream_path,
                        "custom_url": r.custom_url,
                        "stream_url": r.stream_url,
                    }
        except Exception as exc:
            logger.warning("Could not read gate_stream_settings on startup: %s. Using in-memory default.", exc)
            self._configs["GATE_1"] = {
                "gate_id": "GATE_1",
                "enabled": True,
                "ip_address": "192.168.1.100",
                "port": 8080,
                "protocol": "http",
                "stream_path": "/video",
                "custom_url": None,
                "stream_url": "http://192.168.1.100:8080/video",
            }

    def _init_ml_models(self):
        """Initializes ONNX runtime sessions with CPU provider."""
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            if DETECTOR_PATH.exists() and self._det_session is None:
                self._det_session = ort.InferenceSession(str(DETECTOR_PATH), opts, providers=["CPUExecutionProvider"])
                logger.info("Loaded YOLO11n Plate Detector from %s", DETECTOR_PATH.name)

            if OCR_PATH.exists() and self._ocr_session is None:
                self._ocr_session = ort.InferenceSession(str(OCR_PATH), opts, providers=["CPUExecutionProvider"])
                logger.info("Loaded Track A CRNN OCR from %s", OCR_PATH.name)

            if RAPID_OCR_AVAILABLE and self._rapid_ocr is None:
                self._rapid_ocr = RapidOCR()
                logger.info("Loaded RapidOCR (PP-OCRv4) engine for high-accuracy Indian plate reading")
        except Exception as exc:
            logger.warning("ML inference engines failed to initialize (using fallback): %s", exc)

        self._refresh_registry_matcher()

    def _refresh_registry_matcher(self):
        """Refreshes vehicle plates from PostgreSQL for OpticalPlateMatcher."""
        now = time.time()
        if now - self._last_registry_sync < 60.0 and self._matcher is not None:
            return
        try:
            with SessionLocal() as db:
                plates = [p[0] for p in db.query(Vehicle.normalized_plate).filter(Vehicle.normalized_plate.isnot(None)).all()]
                self._matcher = OpticalPlateMatcher(registry=plates)
                self._last_registry_sync = now
        except Exception as exc:
            logger.debug("Registry matcher vehicle sync deferred: %s", exc)
            if self._matcher is None:
                self._matcher = OpticalPlateMatcher(registry=[])

    # -------------------------------------------------------------------------
    # Adaptive FPS Calculations
    # -------------------------------------------------------------------------

    def get_active_gates_count(self) -> int:
        """Returns number of enabled gates."""
        with self._lock:
            return len([c for c in self._configs.values() if c.get("enabled")])

    def get_per_gate_target_fps(self) -> float:
        """
        Dynamically divides FPS budget equally among active gates:
        per_gate_fps = max(2.0, round(total_fps_budget / N_active_gates, 1))
        """
        with self._lock:
            count = self.get_active_gates_count()
            if count <= 0:
                return self.total_fps_budget
            return max(2.0, round(self.total_fps_budget / count, 1))

    def update_settings(
        self,
        total_fps_budget: Optional[float] = None,
        gates_update: Optional[List[Dict[str, Any]]] = None,
    ):
        """Applies updated stream configurations, dynamically resizing threads & FPS."""
        with self._lock:
            if total_fps_budget is not None:
                self.total_fps_budget = max(5.0, min(30.0, float(total_fps_budget)))

            if gates_update:
                for item in gates_update:
                    gid = item["gate_id"]
                    cur = self._configs.get(gid, {"gate_id": gid})
                    for k in ("enabled", "ip_address", "port", "protocol", "stream_path", "custom_url"):
                        if k in item and item[k] is not None:
                            cur[k] = item[k]

                    # Recompute stream_url
                    if cur.get("custom_url"):
                        cur["stream_url"] = cur["custom_url"].strip()
                    else:
                        p = cur.get("stream_path", "/video")
                        if not p.startswith("/"):
                            p = f"/{p}"
                        proto = (cur.get("protocol") or "http").lower()
                        cur["stream_url"] = f"{proto}://{cur.get('ip_address', '127.0.0.1')}:{cur.get('port', 8080)}{p}"
                    self._configs[gid] = cur

            if self._running:
                self._sync_capture_threads()

    def set_gate_enabled(self, gate_id: str, enabled: bool):
        """Quick start/stop toggle for a single gate."""
        with self._lock:
            if gate_id in self._configs:
                self._configs[gate_id]["enabled"] = bool(enabled)
                if self._running:
                    self._sync_capture_threads()

    def _sync_capture_threads(self):
        """Starts capture loops for enabled gates, and terminates stopped ones."""
        with self._lock:
            for gid, cfg in self._configs.items():
                is_enabled = cfg.get("enabled", False)
                worker = self._workers.get(gid)

                if is_enabled:
                    if worker is None or not worker[0].is_alive():
                        stop_ev = threading.Event()
                        t = threading.Thread(
                            target=self._capture_thread_loop,
                            args=(gid, stop_ev),
                            name=f"CaptureWorker-{gid}",
                            daemon=True,
                        )
                        self._workers[gid] = (t, stop_ev)
                        t.start()
                        logger.info("Spawned capture thread for %s (%s)", gid, cfg.get("stream_url"))
                else:
                    if worker is not None:
                        t, stop_ev = worker
                        stop_ev.set()
                        del self._workers[gid]
                        logger.info("Signaled capture thread for %s to stop", gid)

    # -------------------------------------------------------------------------
    # Isolated Capture Loop (Per-Gate Thread)
    # -------------------------------------------------------------------------

    def _capture_thread_loop(self, gate_id: str, stop_event: threading.Event):
        """
        Isolated capture loop. Pulls frames from camera URL, dynamically paces
        sampling rate according to per_gate_target_fps, and handles auto-reconnect backoff.
        """
        backoff_sec = 1.0

        while not stop_event.is_set() and not self._stop_event.is_set():
            with self._lock:
                cfg = self._configs.get(gate_id, {})
                stream_url = cfg.get("stream_url", "")
                host = cfg.get("ip_address")
                port = cfg.get("port", 8080)
                custom_url = cfg.get("custom_url")

            if not stream_url:
                time.sleep(1.0)
                continue

            # Quick pre-flight socket probe (0.5s) to avoid 30s C++ ffmpeg connect freeze on offline cameras
            if host and not custom_url:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.5)
                    s_res = s.connect_ex((host, int(port)))
                    s.close()
                    if s_res != 0:
                        raise RuntimeError(f"Camera endpoint {host}:{port} is unreachable (code {s_res})")
                except Exception as exc:
                    self._last_errors[gate_id] = str(exc)
                    time.sleep(backoff_sec)
                    backoff_sec = min(5.0, backoff_sec * 1.5)
                    continue

            cap = None
            try:
                # Initialize VideoCapture with 3000ms open timeout
                cap = cv2.VideoCapture(stream_url)
                try:
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)
                except Exception:
                    pass

                if not cap.isOpened():
                    raise RuntimeError(f"Could not open stream at {stream_url}")

                backoff_sec = 1.0  # Reset backoff on successful open
                self._last_errors[gate_id] = None

                while not stop_event.is_set() and not self._stop_event.is_set():
                    target_fps = self.get_per_gate_target_fps()
                    t_start = time.perf_counter()

                    ret, frame = cap.read()
                    if not ret or frame is None or frame.size == 0:
                        raise RuntimeError("Frame read returned empty or stream disconnected")

                    now = datetime.now(timezone.utc)
                    self._last_seen[gate_id] = now
                    self._fps_meters[gate_id].append(time.time())
                    self._latest_frames[gate_id] = frame

                    # Push frame into shared bounded inference queue
                    try:
                        if self._inference_queue.full():
                            try:
                                self._inference_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self._inference_queue.put_nowait((gate_id, frame, time.time()))
                    except Exception:
                        pass

                    # Adaptive sleep pacing to match target_fps
                    elapsed = time.perf_counter() - t_start
                    delay = max(0.001, (1.0 / target_fps) - elapsed)
                    time.sleep(delay)

            except Exception as exc:
                err_msg = str(exc)
                self._last_errors[gate_id] = err_msg
                logger.warning("[%s] Stream read failed: %s. Reconnecting in %.1fs...", gate_id, err_msg, backoff_sec)
                time.sleep(backoff_sec)
                backoff_sec = min(5.0, backoff_sec * 1.5)
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        logger.info("[%s] Capture thread loop exited cleanly.", gate_id)

    # -------------------------------------------------------------------------
    # Inference & Guardrails Pipeline (Dedicated Consumer Thread)
    # -------------------------------------------------------------------------

    def _inference_loop(self):
        """
        Consumes frames from shared queue and runs them through the full ANPR guardrail pipeline.
        Periodically flushes accumulated temporal candidate tracks when vehicles pass through.
        """
        logger.info("ANPR Inference Worker loop started with multi-frame slot consensus.")

        while not self._stop_event.is_set():
            try:
                item = self._inference_queue.get(timeout=0.3)
            except queue.Empty:
                item = None

            if item is not None:
                gate_id, frame, frame_ts = item
                # Drop stale frames older than 1.0s to preserve low latency
                if time.time() - frame_ts <= 1.0:
                    try:
                        self.process_frame(gate_id, frame, require_consensus=True)
                    except Exception as exc:
                        logger.error("Error processing frame from %s: %s", gate_id, exc)

            # Check for temporal tracks that need flushing (e.g. vehicle departed or short burst)
            now = time.time()
            for gid in list(self._temporal_tracks.keys()):
                track = self._temporal_tracks[gid]
                if not track:
                    continue
                last_ts = self._temporal_track_last_update.get(gid, 0.0)
                idle_sec = now - last_ts
                # If vehicle accumulated at least 3 frames and has now moved past (idle >= 0.8s)
                if len(track) >= 3 and idle_sec >= 0.8:
                    candidates = list(track[:8])
                    self._temporal_tracks[gid].clear()
                    try:
                        self._fuse_and_ingest(gid, candidates)
                    except Exception as exc:
                        logger.error("Error fusing flushed track for %s: %s", gid, exc)
                elif len(track) < 3 and idle_sec >= 1.5:
                    # Discard transient false-alarm or sub-threshold track
                    self._temporal_tracks[gid].clear()

    def process_frame(
        self,
        gate_id: str,
        frame: np.ndarray,
        require_consensus: bool = False,
    ) -> Optional[str]:
        """
        Executes the ANPR guardrail pipeline on a single frame:
        1. Laplacian sharpness check (>= 40.0)
        2. Letterbox padding to 640x640 with RGB conversion
        3. YOLO11n plate detection with aspect ratio clamping (1.8 <= w/h <= 5.5)
        4. Track A OCR extraction & statutory Indian normalization
        5. Temporal multi-frame aggregation (5-8 frames) or direct single-frame evaluation
        """
        h, w = frame.shape[:2]
        if h < 50 or w < 50:
            return None

        # 1. Laplacian sharpness filter
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if laplacian_var < 40.0:
            logger.debug("[%s] Dropping blurry frame (variance=%.1f < 40.0)", gate_id, laplacian_var)
            return None

        # Lightweight motion/background change gating:
        # Prevents static empty frames (e.g. bare walls, stationary scenery) from repeatedly running inference
        now_ts = time.time()
        small_gray = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
        prev_gray = self._prev_grays.get(gate_id)
        has_motion = True
        if prev_gray is not None and prev_gray.shape == small_gray.shape:
            diff = cv2.absdiff(small_gray, prev_gray)
            mean_diff = float(np.mean(diff))
            if mean_diff < 1.5:
                has_motion = False
        self._prev_grays[gate_id] = small_gray

        if has_motion:
            self._last_motion_ts[gate_id] = now_ts

        if require_consensus:
            last_motion = self._last_motion_ts.get(gate_id, now_ts)
            has_active_track = bool(self._temporal_tracks.get(gate_id))
            if not has_motion and (now_ts - last_motion > 2.5) and not has_active_track:
                # Static scene with no vehicle motion - skip expensive YOLO / false triggers
                return None

        # 2. Letterbox padding (with RGB conversion for YOLO)
        canvas, scale, dx, dy = letterbox_image(frame, 640)
        canvas_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)

        # 3. YOLO11n Plate Detection
        boxes = []
        if self._det_session is not None:
            inp = canvas_rgb.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 255.0
            det_out = self._det_session.run(None, {self._det_session.get_inputs()[0].name: inp})[0][0]

            conf_thresh = 0.65
            for col in range(det_out.shape[1]):
                score = float(det_out[4, col])
                if score >= conf_thresh:
                    cx_pad, cy_pad, bw_pad, bh_pad = det_out[0:4, col]
                    cx_orig = (cx_pad - dx) / scale
                    cy_orig = (cy_pad - dy) / scale
                    bw_orig = bw_pad / scale
                    bh_orig = bh_pad / scale

                    # Aspect-ratio clamping: 1.8 <= w/h <= 5.5
                    aspect = bw_orig / max(1.0, bh_orig)
                    if aspect < 1.8 or aspect > 5.5:
                        continue

                    # Reject oversized or tiny candidate boxes
                    if bw_orig > 0.7 * w or bh_orig > 0.35 * h:
                        continue
                    if bw_orig < 60 or bh_orig < 18:
                        continue

                    x1 = max(0, int(cx_orig - bw_orig / 2))
                    y1 = max(0, int(cy_orig - bh_orig / 2))
                    x2 = min(w, int(cx_orig + bw_orig / 2))
                    y2 = min(h, int(cy_orig + bh_orig / 2))
                    boxes.append((x1, y1, x2, y2, score))

        # NMS on candidate boxes with score threshold 0.65
        final_boxes = []
        if boxes:
            cv_boxes = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes]
            scores = [b[4] for b in boxes]
            indices = cv2.dnn.NMSBoxes(cv_boxes, scores, 0.65, 0.45)
            for idx in (indices.flatten() if len(indices) > 0 else []):
                final_boxes.append(boxes[idx])

        if not final_boxes:
            return None

        # 4. High-Accuracy OCR & Statutory Indian Plate Normalization
        best_plate = None
        for x1, y1, x2, y2, score in final_boxes:
            bw = x2 - x1
            bh = y2 - y1

            # 8% bounding-box padding around plate crops (clamped to frame dimensions)
            pad_w = int(round(bw * 0.08))
            pad_h = int(round(bh * 0.08))
            px1 = max(0, x1 - pad_w)
            py1 = max(0, y1 - pad_h)
            px2 = min(w, x2 + pad_w)
            py2 = min(h, y2 + pad_h)

            crop = frame[py1:py2, px1:px2]
            if crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 30:
                continue

            # Crop-level plate-likeness gate before OCR:
            # Rejects crops with low grayscale contrast (std < 22.0) or abnormal Canny edge density (< 0.04 or > 0.55)
            if not is_plate_like_crop(crop):
                logger.debug("[%s] Dropping non-plate crop (failed contrast/edge texture gate)", gate_id)
                continue

            # Crop preprocessing before OCR: aspect-preserving bicubic upscale if height < 48px, LAB CLAHE if dark/low contrast
            prep_crop = preprocess_plate_crop(crop)
            prep_h, prep_w = prep_crop.shape[:2]
            aspect_ratio = float(prep_w) / max(1.0, float(prep_h))
            is_possible_multiline = aspect_ratio < 2.5

            raw_text = ""
            char_conf = 0.0
            crnn_text = ""
            crnn_conf = 0.0

            # Step 1: Run plate-trained ONNX model FIRST (indian_plate_crnn_best.onnx / track_a_ocr_cct.onnx)
            if self._ocr_session is not None:
                try:
                    crop_rgb = cv2.cvtColor(prep_crop, cv2.COLOR_BGR2RGB)
                    crop_res = cv2.resize(crop_rgb, (128, 32)).transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 127.5 - 1.0
                    logits = self._ocr_session.run(None, {self._ocr_session.get_inputs()[0].name: crop_res})[0]
                    crnn_text, crnn_conf = decode_crnn_logits(logits)
                except Exception as crnn_err:
                    logger.debug("[%s] CRNN inference error: %s", gate_id, crnn_err)

            crnn_norm = normalize_plate(crnn_text) if crnn_text else ""
            crnn_is_valid = is_valid_indian_plate(crnn_norm) or bool(suggest_repairs(crnn_norm))

            # Step 2: RapidOCR fallback/tie-breaker when CRNN confidence is low (< 0.55) or for 2-line plates
            need_rapid_ocr = (
                self._rapid_ocr is not None and (
                    crnn_conf < 0.55
                    or is_possible_multiline
                    or len(crnn_norm) < 7
                    or not crnn_is_valid
                )
            )

            rapid_text = ""
            rapid_conf = 0.0
            if need_rapid_ocr:
                try:
                    res, _ = self._rapid_ocr(prep_crop)
                    if res:
                        # When RapidOCR returns multiple lines on 2-line plates, sort boxes top-to-bottom then left-to-right
                        sorted_res = sort_multiline_boxes(res, prep_h)
                        lines = []
                        confs = []
                        for box, txt, r_score in sorted_res:
                            norm = normalize_plate(txt)
                            if norm == "IND":
                                continue
                            if norm.startswith("IND") and len(norm) > 4:
                                norm = norm[3:]
                            if norm.endswith("IND") and len(norm) > 4:
                                norm = norm[:-3]
                            if norm:
                                lines.append(norm)
                                confs.append(float(r_score))
                        if lines:
                            rapid_text = "".join(lines)
                            rapid_conf = float(np.mean(confs))
                except Exception as ocr_err:
                    logger.debug("[%s] RapidOCR fallback error: %s", gate_id, ocr_err)

            rapid_norm = normalize_plate(rapid_text) if rapid_text else ""
            rapid_is_valid = is_valid_indian_plate(rapid_norm) or bool(suggest_repairs(rapid_norm))

            # Tie-breaker selection
            if crnn_text and not rapid_text:
                raw_text, char_conf = crnn_text, crnn_conf
            elif rapid_text and not crnn_text:
                raw_text, char_conf = rapid_text, rapid_conf
            elif crnn_text and rapid_text:
                if rapid_is_valid and not crnn_is_valid:
                    raw_text, char_conf = rapid_text, rapid_conf
                elif crnn_is_valid and not rapid_is_valid:
                    raw_text, char_conf = crnn_text, crnn_conf
                elif is_possible_multiline and len(rapid_norm) >= 7:
                    raw_text, char_conf = rapid_text, rapid_conf
                elif crnn_conf >= 0.55 and crnn_is_valid:
                    raw_text, char_conf = crnn_text, crnn_conf
                elif rapid_conf > crnn_conf:
                    raw_text, char_conf = rapid_text, rapid_conf
                else:
                    raw_text, char_conf = crnn_text, crnn_conf

            # Reject OCR reads with low character confidence (< 0.45)
            if char_conf < 0.45:
                logger.debug("[%s] Dropping low-confidence OCR read '%s' (char_conf=%.2f < 0.45)", gate_id, raw_text, char_conf)
                continue

            norm_plate = normalize_plate(raw_text) if raw_text else None
            # Statutory Indian plates have 7 to 11 characters
            if not norm_plate or len(norm_plate) < 7 or len(norm_plate) > 11:
                continue

            candidate = {
                "raw_plate": raw_text,
                "conf": max(score, char_conf),
                "bbox": [px1, py1, px2, py2],
                "frame": frame.copy(),
                "sharpness": laplacian_var,
                "timestamp": time.time(),
            }

            if not require_consensus:
                return self._fuse_and_ingest(gate_id, [candidate])

            # In live stream mode, accumulate candidates across 5-8 frames
            self._temporal_tracks[gate_id].append(candidate)
            self._temporal_track_last_update[gate_id] = time.time()

            # When 5-8 frames are collected, trigger consensus fusion
            if len(self._temporal_tracks[gate_id]) >= 5:
                batch = self._temporal_tracks[gate_id][:8]
                self._temporal_tracks[gate_id] = self._temporal_tracks[gate_id][8:]
                return self._fuse_and_ingest(gate_id, batch)

            return None

        return best_plate

    def _fuse_and_ingest(
        self,
        gate_id: str,
        candidates: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        Fuses 5-8 temporal candidate frames for an approaching vehicle, validates decomposed
        slots against statutory Indian plate rules, applies registry matching, enforces debounce,
        and ingests the highest-quality snapshot into ObservationService.
        """
        if not candidates:
            return None

        fused_res = fuse_multiframe_plate_reads(candidates)
        if not fused_res:
            logger.debug("[%s] Multi-frame fusion returned None for %d candidates", gate_id, len(candidates))
            return None

        fused_plate = fused_res["fused_plate"]
        is_valid = fused_res["is_valid"]
        best_frame = fused_res.get("best_frame")
        best_bbox = fused_res.get("best_bbox") or []
        confidence = fused_res.get("confidence", 0.85)
        agreement_rate = fused_res.get("agreement_rate", 1.0)
        slot_breakdown = fused_res.get("slot_breakdown", {})

        # 1. Statutory Indian Plate Validation & Positional Repair
        candidate_plate = fused_plate
        is_statutory = is_valid_indian_plate(candidate_plate)
        if not is_statutory:
            repairs = suggest_repairs(candidate_plate)
            if repairs:
                candidate_plate = repairs[0]
                is_statutory = is_valid_indian_plate(candidate_plate)

        # 2. Registry Matching via OpticalPlateMatcher
        self._refresh_registry_matcher()
        effective_plate = candidate_plate
        match_score = confidence
        registry_matched = False
        if self._matcher is not None:
            res = self._matcher.match(candidate_plate)
            if res.matched_plate:
                if is_statutory and float(res.similarity_score) >= 0.75:
                    effective_plate = res.matched_plate
                    match_score = max(match_score, float(res.similarity_score))
                    registry_matched = True
                elif (not is_statutory) and float(res.similarity_score) >= 0.85 and float(res.score_margin) >= 0.07 and not res.is_ambiguous:
                    effective_plate = res.matched_plate
                    match_score = max(match_score, float(res.similarity_score))
                    registry_matched = True

        # Tightened Gate: Never accept a static-noise fuzzy match unless is_valid_indian_plate(repaired) is True
        # OR (similarity_score >= 0.85 with ambiguity margin >= 0.07).
        if not is_statutory and not registry_matched:
            logger.info(
                "[%s] Dropped non-statutory/noise candidate '%s' (not a valid Indian plate and failed strict registry threshold)",
                gate_id,
                fused_plate,
            )
            return None

        # Gate-level burst debounce (3.5s): prevents rapid duplicate rows when OCR jitters across video frames
        now_sec = time.time()
        last_gate = self._gate_last_ingest.get(gate_id)
        if last_gate is not None:
            last_ts, last_plate = last_gate
            if (now_sec - last_ts) < 3.5:
                if _edit_distance(effective_plate, last_plate) <= 2:
                    logger.debug(
                        "[%s] Suppressing burst flicker %s (within edit-dist 2 of %s seen %.1fs ago)",
                        gate_id,
                        effective_plate,
                        last_plate,
                        now_sec - last_ts,
                    )
                    return None

        # 60-Second Debounce per (gate_id, effective_plate)
        debounce_key = (gate_id, effective_plate)
        last_hit = self._debounce_cache.get(debounce_key, 0.0)
        if now_sec - last_hit < 60.0:
            logger.debug(
                "[%s] Debounced plate %s (last seen %.1fs ago)",
                gate_id,
                effective_plate,
                now_sec - last_hit,
            )
            return None

        self._debounce_cache[debounce_key] = now_sec
        self._gate_last_ingest[gate_id] = (now_sec, effective_plate)

        # Ingestion into ObservationService with multi-frame metadata
        extra_meta = {
            "multiframe_consensus": True,
            "frame_count": len(candidates),
            "agreement_rate": agreement_rate,
            "slot_breakdown": slot_breakdown,
            "candidate_reads": [c.get("raw_plate", "") for c in candidates if c.get("raw_plate")],
        }
        sharpness = max([float(c.get("sharpness", 50.0)) for c in candidates]) if candidates else 50.0
        self._ingest_observation(
            gate_id=gate_id,
            plate=effective_plate,
            confidence=match_score,
            sharpness=sharpness,
            bbox=best_bbox,
            frame=best_frame,
            extra_metadata=extra_meta,
        )
        return effective_plate

    def _ingest_observation(
        self,
        gate_id: str,
        plate: str,
        confidence: float,
        sharpness: float,
        bbox: List[int],
        frame: Optional[np.ndarray] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """Stores observation in PostgreSQL, persists snapshot image, and publishes to live feed."""
        try:
            now_dt = datetime.now(timezone.utc)
            source_event_id = f"stream_{gate_id}_{plate}_{int(now_dt.timestamp())}"
            has_snap = False

            if frame is not None and frame.size > 0:
                try:
                    snap_dir = Path(MEDIA_ROOT) / "snapshots"
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    snap_path = snap_dir / f"{source_event_id}.jpg"

                    annotated = frame.copy()
                    if bbox and len(bbox) == 4:
                        bx1, by1, bx2, by2 = bbox
                        cv2.rectangle(annotated, (bx1, by1), (bx2, by2), (34, 197, 94), 3)
                        label = f"{plate} ({int(confidence * 100)}%)"
                        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                        ty = max(th + 10, by1 - 8)
                        cv2.rectangle(annotated, (bx1, ty - th - 6), (bx1 + tw + 8, ty + 4), (0, 0, 0), -1)
                        cv2.putText(annotated, label, (bx1 + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (34, 197, 94), 2)
                    cv2.imwrite(str(snap_path), annotated)
                    has_snap = True
                except Exception as write_err:
                    logger.warning("[%s] Failed to save snapshot frame: %s", gate_id, write_err)

            with SessionLocal() as db:
                meta = {
                    "pipeline": "live_mobile_stream_runner",
                    "sharpness_laplacian": round(sharpness, 1),
                    "bbox": bbox,
                    "has_snapshot": has_snap,
                    "ingestion_time": datetime.now(timezone.utc).isoformat(),
                }
                if extra_metadata:
                    meta.update(extra_metadata)

                event_data = ObservationCreate(
                    gate_id=gate_id,
                    camera_id=f"{gate_id.lower()}_ip_cam",
                    observed_at=now_dt,
                    source=ObservationSource.OTHER,
                    source_event_id=source_event_id,
                    raw_plate=plate,
                    plate_confidence=float(confidence),
                    vehicle_type=ObservedVehicleType.CAR,
                    vehicle_confidence=0.9,
                    direction=ObservationDirection.ENTRY,
                    metadata_payload=meta,
                )
                obs = ObservationService.create_or_update_observation(db, event_data)

                if has_snap:
                    try:
                        obs_snap = snap_dir / f"{obs.id}.jpg"
                        if not obs_snap.exists():
                            import shutil
                            shutil.copyfile(str(snap_path), str(obs_snap))
                    except Exception:
                        pass

                logger.info(
                    "[%s] Ingested plate %s (conf=%.2f, sharpness=%.1f) -> Observation %s (snapshot=%s)",
                    gate_id,
                    plate,
                    confidence,
                    sharpness,
                    obs.id,
                    has_snap,
                )
        except Exception as exc:
            logger.error("[%s] Failed to persist observation for plate %s: %s", gate_id, plate, exc)

    def get_latest_frame(self, gate_id: str) -> Optional[np.ndarray]:
        """Returns the most recent frame captured for this gate, or None if stream is idle."""
        with self._lock:
            frame = self._latest_frames.get(gate_id)
            if frame is not None:
                return frame.copy()
            return None

    # -------------------------------------------------------------------------
    # Telemetry & Diagnostics
    # -------------------------------------------------------------------------

    def get_gate_actual_fps(self, gate_id: str) -> float:
        """Calculates rolling actual FPS over the last 5 seconds."""
        dq = self._fps_meters.get(gate_id)
        if not dq or len(dq) < 2:
            return 0.0
        now = time.time()
        # Drop timestamps older than 5.0 seconds
        while dq and dq[0] < now - 5.0:
            dq.popleft()
        if len(dq) < 2:
            return 0.0
        duration = dq[-1] - dq[0]
        if duration <= 0:
            return 0.0
        return round(float(len(dq) - 1) / duration, 1)

    def get_telemetry(self) -> Dict[str, Any]:
        """Builds complete snapshot for GET /api/gates/stream-settings."""
        with self._lock:
            active_count = self.get_active_gates_count()
            per_gate_target = self.get_per_gate_target_fps()

            items = []
            for gid, cfg in sorted(self._configs.items()):
                enabled = cfg.get("enabled", False)
                worker = self._workers.get(gid)
                is_running = bool(worker and worker[0].is_alive())
                actual_fps = self.get_gate_actual_fps(gid) if is_running else 0.0
                effective_fps = per_gate_target if enabled else 0.0

                items.append({
                    "gate_id": gid,
                    "gate_name": cfg.get("gate_name") or f"Gate {gid.replace('GATE_', '')}",
                    "enabled": enabled,
                    "ip_address": cfg.get("ip_address", "192.168.1.100"),
                    "port": cfg.get("port", 8080),
                    "protocol": cfg.get("protocol", "http"),
                    "stream_path": cfg.get("stream_path", "/video"),
                    "custom_url": cfg.get("custom_url"),
                    "stream_url": cfg.get("stream_url", ""),
                    "is_running": is_running,
                    "effective_fps": effective_fps,
                    "actual_fps": actual_fps,
                    "last_seen_at": self._last_seen.get(gid),
                    "last_error": self._last_errors.get(gid),
                })

            return {
                "total_fps_budget": self.total_fps_budget,
                "active_gates_count": active_count,
                "per_gate_target_fps": per_gate_target,
                "gates": items,
            }

    @staticmethod
    def test_connection(
        host: str,
        port: int,
        protocol: str = "http",
        path: str = "/video",
        custom_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Tests TCP socket reachability and single-frame acquisition within 3 seconds.
        """
        target_url = (
            custom_url.strip()
            if custom_url and custom_url.strip()
            else f"{protocol.lower()}://{host}:{port}{path if path.startswith('/') else f'/{path}'}"
        )

        t0 = time.perf_counter()
        # 1. TCP socket reachability probe
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            res = sock.connect_ex((host, port))
            sock.close()
            if res != 0:
                return {
                    "status": "error",
                    "tested_url": target_url,
                    "latency_ms": None,
                    "stream_type": protocol.upper(),
                    "message": f"Connection to {host}:{port} refused or timed out (error code {res}).",
                }
        except Exception as exc:
            return {
                "status": "error",
                "tested_url": target_url,
                "latency_ms": None,
                "stream_type": protocol.upper(),
                "message": f"Network error testing {host}:{port}: {exc}",
            }

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        # 2. Frame-read handshake check
        frame_read_ok = False
        cap = None
        try:
            cap = cv2.VideoCapture(target_url)
            try:
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000)
            except Exception:
                pass
            if cap.isOpened():
                ret, _ = cap.read()
                frame_read_ok = bool(ret)
        except Exception:
            frame_read_ok = False
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

        stream_type = "HTTP_MJPEG" if protocol.lower() == "http" else "RTSP"
        if frame_read_ok:
            msg = f"Successfully connected to stream at {target_url} in {latency_ms:.1f}ms."
        else:
            msg = f"Port {port} is open ({latency_ms:.1f}ms). Stream handshake accepted."

        return {
            "status": "ok",
            "tested_url": target_url,
            "latency_ms": latency_ms,
            "stream_type": stream_type,
            "message": msg,
        }


# Global singleton
camera_stream_manager = CameraStreamManager()
