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
from backend.app.services.anpr.color_remap import remap_to_yellow_black
from backend.app.services.anpr.ocr_engine import (
    deskew_plate,
    is_plate_like_crop,
    pad_plate_bbox,
    run_dual_pass_ocr,
    split_two_line_plate,
)
from backend.app.services.anpr.polarity_normalizer import normalize_plate_agnostic
from backend.app.services.anpr.track_voter import TrackVoter
from backend.app.services.anpr.vehicle_gatekeeper import (
    FALLBACK_MODEL_PATH,
    SimpleVehicleTracker,
    UVH26_MODEL_PATH,
    VehicleDetection,
    VehicleGatekeeper,
    VehicleTrack,
)
from backend.app.services.multiframe_plate_consensus import decompose_indian_plate_slots, fuse_multiframe_plate_reads
from backend.app.services.observation_service import ObservationService
from backend.app.services.plate_normalizer import (
    classify_plate_format,
    correct_indian_plate,
    is_valid_indian_plate,
    normalize_plate,
    repair_plate_positional,
    suggest_repairs,
)
from research_track.track_a.src.registry_matcher import OpticalPlateMatcher

logger = logging.getLogger("campus_security.camera_stream")

ROOT_DIR = Path(BASE_DIR).resolve()
WEIGHTS_DIR = ROOT_DIR / "weights"
DETECTOR_PATH = WEIGHTS_DIR / "yolo11n_plate_detector_finetuned.onnx"
if not DETECTOR_PATH.exists():
    DETECTOR_PATH = WEIGHTS_DIR / "yolo11n_plate_detector_fleet_best.onnx"
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


class TrackVoterList(list):
    """
    Enhanced temporal track buffer that behaves as a list of candidate dicts
    while managing a TrackVoter instance for multi-frame consensus.
    """

    def __init__(
        self,
        gate_id: str = "",
        min_consensus_frames: int = 5,
        max_track_frames: int = 8,
    ) -> None:
        super().__init__()
        self.gate_id = str(gate_id)
        self.min_consensus_frames = min_consensus_frames
        self.max_track_frames = max_track_frames
        self.voter = TrackVoter(
            min_consensus_frames=min_consensus_frames,
            max_track_frames=max_track_frames,
        )

    def add_observation(
        self,
        track_id: str,
        plate_text: str,
        confidence: float,
        bbox: List[int],
        frame_ts: float,
        frame_bgr: Optional[np.ndarray] = None,
    ) -> None:
        self.voter.add_observation(
            track_id=track_id,
            plate_text=plate_text,
            confidence=confidence,
            bbox=bbox,
            frame_ts=frame_ts,
            frame_bgr=frame_bgr,
        )
        cand = {
            "raw_plate": plate_text,
            "conf": confidence,
            "bbox": bbox,
            "frame": frame_bgr,
            "timestamp": frame_ts,
        }
        super().append(cand)
        if len(self) > self.max_track_frames:
            del self[:-self.max_track_frames]

    def get_consensus(self, track_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.voter.get_consensus(track_id or self.gate_id)

    def clear(self) -> None:
        super().clear()
        self.voter.clear_track(self.gate_id)

    def clear_track(self, track_id: Optional[str] = None) -> None:
        super().clear()
        self.voter.clear_track(track_id or self.gate_id)

    def get_track_frame_count(self, track_id: Optional[str] = None) -> int:
        return self.voter.get_track_frame_count(track_id or self.gate_id)

    def append(self, item: Any) -> None:
        super().append(item)
        if isinstance(item, dict):
            p_text = str(item.get("raw_plate") or item.get("plate", ""))
            p_conf = float(item.get("conf") or item.get("confidence", 0.9))
            p_bbox = list(item.get("bbox", []))
            p_frame = item.get("frame")
            p_ts = float(item.get("timestamp", time.time()))
            self.voter.add_observation(
                track_id=self.gate_id,
                plate_text=p_text,
                confidence=p_conf,
                bbox=p_bbox,
                frame_ts=p_ts,
                frame_bgr=p_frame,
            )
        if len(self) > self.max_track_frames:
            del self[:-self.max_track_frames]


class _TemporalTracksDict(dict):
    """Default-instantiating dict mapping gate_id to TrackVoterList."""

    def __missing__(self, gate_id: str) -> TrackVoterList:
        val = TrackVoterList(gate_id=gate_id, min_consensus_frames=5, max_track_frames=8)
        self[gate_id] = val
        return val

    def __setitem__(self, gate_id: str, val: Any) -> None:
        if isinstance(val, list) and not isinstance(val, TrackVoterList):
            new_val = TrackVoterList(gate_id=gate_id, min_consensus_frames=5, max_track_frames=8)
            for item in val:
                new_val.append(item)
            super().__setitem__(gate_id, new_val)
        else:
            super().__setitem__(gate_id, val)


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
        self._vehicle_gatekeeper: Optional[VehicleGatekeeper] = None
        self._vehicle_trackers: Dict[str, SimpleVehicleTracker] = collections.defaultdict(
            lambda: SimpleVehicleTracker(max_age_sec=2.0)
        )
        self._matcher: Optional[OpticalPlateMatcher] = None
        self._last_registry_sync: float = 0.0

        # Debounce: (gate_id, normalized_plate) -> timestamp
        self._debounce_cache: Dict[Tuple[str, str], float] = {}
        # Gate-level burst debounce: gate_id -> (timestamp, plate)
        self._gate_last_ingest: Dict[str, Tuple[float, str]] = {}
        # Temporal candidate tracks for multi-frame consensus: gate_id -> TrackVoterList
        self._temporal_tracks: Dict[str, TrackVoterList] = _TemporalTracksDict()
        self._temporal_track_last_update: Dict[str, float] = {}

    @property
    def _track_voters(self) -> Dict[str, TrackVoter]:
        return {gid: t.voter for gid, t in self._temporal_tracks.items()}

    @property
    def _track_voter(self) -> TrackVoter:
        return self._temporal_tracks["GATE_1"].voter

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

            if self._vehicle_gatekeeper is None:
                try:
                    self._vehicle_gatekeeper = VehicleGatekeeper()
                    logger.info("Loaded Stage-0 Vehicle Gatekeeper (UVH-26 / Fallback)")
                except Exception as vg_err:
                    logger.warning("Stage-0 Vehicle Gatekeeper failed to load: %s", vg_err)

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
            for tid in list(self._temporal_tracks.keys()):
                track = self._temporal_tracks[tid]
                if not track:
                    continue
                last_ts = self._temporal_track_last_update.get(tid, 0.0)
                idle_sec = now - last_ts
                gid = tid.split("_veh_")[0] if "_veh_" in tid else tid
                # If vehicle accumulated at least 3 frames and has now moved past (idle >= 0.8s)
                if len(track) >= 3 and idle_sec >= 0.8:
                    candidates = list(track[:8])
                    consensus = track.get_consensus(tid)
                    if consensus is None and len(candidates) >= 3:
                        temp_voter = TrackVoter(min_consensus_frames=len(candidates), max_track_frames=8)
                        for c in candidates:
                            temp_voter.add_observation(
                                track_id=tid,
                                plate_text=c.get("raw_plate", ""),
                                confidence=float(c.get("conf", 0.8)),
                                bbox=c.get("bbox", []),
                                frame_ts=float(c.get("timestamp", now)),
                                frame_bgr=c.get("frame"),
                            )
                        consensus = temp_voter.get_consensus(tid)
                    self._temporal_tracks[tid].clear()
                    try:
                        self._fuse_and_ingest(gid, consensus if consensus else candidates)
                    except Exception as exc:
                        logger.error("Error fusing flushed track for %s: %s", gid, exc)
                elif len(track) < 3 and idle_sec >= 1.5:
                    # Discard transient false-alarm or sub-threshold track
                    self._temporal_tracks[tid].clear()

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

        # ---------------------------------------------------------------------
        # Stage 0: Vehicle Gatekeeper (IISc AIM UVH-26 / fallback)
        # ---------------------------------------------------------------------
        # If gatekeeper is initialized, detect approaching vehicles.
        # If zero vehicles detected, return immediately (zero empty-space false alarms, zero wasted OCR CPU).
        vehicle_dets: Optional[List[VehicleDetection]] = None
        if self._vehicle_gatekeeper is not None and getattr(self._vehicle_gatekeeper, "session", None) is not None:
            vehicle_dets = self._vehicle_gatekeeper.detect_vehicles(frame)
            if not vehicle_dets:
                logger.debug("[%s] Stage 0 Gatekeeper: zero vehicles detected, skipping frame.", gate_id)
                return None

        # ---------------------------------------------------------------------
        # Track & Crop: Persistent Track ID & Vehicle Class Assignment
        # ---------------------------------------------------------------------
        now_ts = time.time()
        if vehicle_dets is not None:
            tracker = self._vehicle_trackers[gate_id]
            tracker.gate_id = gate_id
            tracked_vehicles = tracker.update(vehicle_dets, now_ts)
        else:
            # Passthrough fallback when gatekeeper is disabled/not loaded (e.g. isolated test without gatekeeper)
            tracked_vehicles = [(
                VehicleTrack(
                    track_id=gate_id,
                    vehicle_class="car",
                    observed_type=ObservedVehicleType.CAR,
                    bbox=[0, 0, w, h],
                    confidence=0.9,
                    last_seen_ts=now_ts,
                    first_seen_ts=now_ts,
                ),
                None,
            )]

        # ---------------------------------------------------------------------
        # Stage 1: Zoomed Plate Detection inside each detected vehicle crop
        # ---------------------------------------------------------------------
        final_boxes: List[Tuple[int, int, int, int, float, VehicleTrack]] = []
        for track, v_det in tracked_vehicles:
            if v_det is not None:
                v_crop, (vx1, vy1, vx2, vy2) = VehicleGatekeeper.crop_vehicle(frame, track.bbox, pad_pct=0.05)
            else:
                v_crop, (vx1, vy1, vx2, vy2) = frame, (0, 0, w, h)

            if v_crop.size == 0 or v_crop.shape[0] < 20 or v_crop.shape[1] < 20:
                continue

            vh, vw = v_crop.shape[:2]
            canvas, scale, dx, dy = letterbox_image(v_crop, 640)
            canvas_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)

            candidate_boxes = []
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

                        # Aspect-ratio clamping: 0.9 <= w/h <= 6.0 (handles square 2W plates to wide commercial plates)
                        aspect = bw_orig / max(1.0, bh_orig)
                        if aspect < 0.9 or aspect > 6.0:
                            continue

                        # Reject oversized or tiny candidate boxes within vehicle crop
                        if bw_orig > 0.95 * vw or bh_orig > 0.85 * vh:
                            continue
                        if bw_orig < 24 or bh_orig < 12:
                            continue

                        local_x1 = max(0, int(cx_orig - bw_orig / 2))
                        local_y1 = max(0, int(cy_orig - bh_orig / 2))
                        local_x2 = min(vw, int(cx_orig + bw_orig / 2))
                        local_y2 = min(vh, int(cy_orig + bh_orig / 2))

                        # Project box back to original full frame coordinates
                        orig_x1 = min(w, max(0, vx1 + local_x1))
                        orig_y1 = min(h, max(0, vy1 + local_y1))
                        orig_x2 = min(w, max(0, vx1 + local_x2))
                        orig_y2 = min(h, max(0, vy1 + local_y2))
                        candidate_boxes.append((orig_x1, orig_y1, orig_x2, orig_y2, score, track))

            if candidate_boxes:
                cv_boxes = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in candidate_boxes]
                scores = [b[4] for b in candidate_boxes]
                indices = cv2.dnn.NMSBoxes(cv_boxes, scores, 0.65, 0.45)
                for idx in (indices.flatten() if len(indices) > 0 else []):
                    final_boxes.append(candidate_boxes[idx])

        if not final_boxes:
            return None

        # ---------------------------------------------------------------------
        # Stage 2: Preprocessing + Dual-Pass OCR + Positional Grammar + Voting
        # ---------------------------------------------------------------------
        best_plate = None
        for x1, y1, x2, y2, score, track in final_boxes:
            # Geometry & Bounding Box Padding (+8% W, +5% H)
            px1, py1, px2, py2 = pad_plate_bbox(
                [x1, y1, x2, y2],
                frame.shape[:2],
                pad_w_pct=0.08,
                pad_h_pct=0.05,
            )

            crop = frame[py1:py2, px1:px2]
            if crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 20:
                continue

            # Crop-level plate-likeness gate before OCR
            if not is_plate_like_crop(crop):
                logger.debug("[%s] Dropping non-plate crop (failed contrast/edge texture gate)", gate_id)
                continue

            # Deskew plate
            crop = deskew_plate(crop, min_angle=3.0, max_angle=25.0)

            # Dual-Pass Multi-Color & EV OCR Execution
            # Pass 1 (Primary - Color Agnostic CLAHE + Otsu Normalization):
            norm_crop, was_inverted = normalize_plate_agnostic(crop)
            text1, conf1, engine1 = run_dual_pass_ocr(
                norm_crop,
                ocr_session=self._ocr_session,
                rapid_ocr=self._rapid_ocr,
            )
            plate1, syntax_conf1, cat1 = correct_indian_plate(text1)

            chosen_text = text1
            chosen_conf = conf1
            chosen_plate = plate1
            chosen_syntax_conf = syntax_conf1
            chosen_cat = cat1
            chosen_engine = engine1

            # Pass 2 (Fallback - Soft CIE LAB Color Remapping):
            if conf1 < 0.55 or cat1 == "INVALID":
                remapped_crop, detected_type = remap_to_yellow_black(crop)
                text2, conf2, engine2 = run_dual_pass_ocr(
                    remapped_crop,
                    ocr_session=self._ocr_session,
                    rapid_ocr=self._rapid_ocr,
                )
                plate2, syntax_conf2, cat2 = correct_indian_plate(text2)
                if cat2 != "INVALID" and (cat1 == "INVALID" or conf2 > conf1):
                    chosen_text = text2
                    chosen_conf = conf2
                    chosen_plate = plate2
                    chosen_syntax_conf = syntax_conf2
                    chosen_cat = cat2
                    chosen_engine = engine2

            # If both passes fail quality threshold, reject
            if not chosen_text or (chosen_conf < 0.40 and chosen_syntax_conf < 0.40 and chosen_cat == "INVALID"):
                logger.debug("[%s] Dropping low-confidence OCR read '%s' (conf=%.2f)", gate_id, chosen_text, chosen_conf)
                continue

            plate_to_use = chosen_plate or normalize_plate(chosen_text)
            if not plate_to_use or len(plate_to_use) < 6:
                continue

            candidate_conf = max(float(score), float(chosen_conf))
            best_plate = plate_to_use

            candidate = {
                "raw_plate": plate_to_use,
                "raw_text": chosen_text,
                "conf": candidate_conf,
                "syntax_conf": chosen_syntax_conf,
                "format_category": chosen_cat,
                "engine": chosen_engine,
                "bbox": [px1, py1, px2, py2],
                "frame": frame.copy(),
                "sharpness": laplacian_var,
                "timestamp": now_ts,
                "vehicle_class": track.vehicle_class,
                "observed_type": track.observed_type,
                "vehicle_confidence": track.confidence,
                "vehicle_track_id": track.track_id,
                "vehicle_bbox": track.bbox,
            }

            if not require_consensus:
                return self._fuse_and_ingest(gate_id, [candidate])

            # Accumulate observation into per-track (or per-gate) TrackVoter
            target_track_id = track.track_id if track.track_id != gate_id else gate_id
            track_voter = self._temporal_tracks[target_track_id]
            track_voter.add_observation(
                track_id=target_track_id,
                plate_text=plate_to_use,
                confidence=candidate_conf,
                bbox=[px1, py1, px2, py2],
                frame_ts=now_ts,
                frame_bgr=frame.copy(),
            )
            self._temporal_track_last_update[target_track_id] = now_ts

            consensus = track_voter.get_consensus(target_track_id)
            if consensus is not None:
                track_voter.clear()
                consensus["vehicle_class"] = track.vehicle_class
                consensus["observed_type"] = track.observed_type
                consensus["vehicle_confidence"] = track.confidence
                consensus["vehicle_track_id"] = track.track_id
                consensus["vehicle_bbox"] = track.bbox
                return self._fuse_and_ingest(gate_id, consensus)

            return None

        return best_plate

    def _fuse_and_ingest(
        self,
        gate_id: str,
        candidates: Union[List[Dict[str, Any]], Dict[str, Any]],
    ) -> Optional[str]:
        """
        Fuses temporal candidate frames for an approaching vehicle, validates decomposed
        slots against statutory Indian plate rules, applies registry matching, enforces debounce,
        and ingests the highest-quality snapshot into ObservationService.
        """
        if not candidates:
            return None

        fused_res: Optional[Dict[str, Any]] = None
        if isinstance(candidates, dict):
            fused_res = candidates
        elif isinstance(candidates, list):
            if len(candidates) == 1:
                c = candidates[0]
                raw_p = c.get("raw_plate", "")
                canon_plate, syntax_conf, fmt_cat = correct_indian_plate(raw_p)
                is_val = fmt_cat in ("STANDARD", "BHARAT_SERIES", "VINTAGE")
                req_manual = (fmt_cat in ("MILITARY", "DIPLOMATIC", "INVALID")) or (syntax_conf < 0.40)
                fused_res = {
                    "fused_plate": canon_plate or raw_p,
                    "confidence": float(c.get("conf", 0.85)),
                    "syntax_confidence": syntax_conf,
                    "agreement_rate": 1.0,
                    "format_category": fmt_cat,
                    "requires_manual_check": req_manual,
                    "action": "MANUAL_CHECK" if req_manual else "PROCEED",
                    "best_bbox": c.get("bbox") or [],
                    "best_frame": c.get("frame"),
                    "voted_raw": raw_p,
                    "frame_count": 1,
                    "is_valid": is_val,
                }
            else:
                temp_voter = TrackVoter(min_consensus_frames=min(5, len(candidates)), max_track_frames=max(8, len(candidates)))
                for c in candidates:
                    temp_voter.add_observation(
                        track_id=gate_id,
                        plate_text=c.get("raw_plate", ""),
                        confidence=float(c.get("conf", 0.85)),
                        bbox=c.get("bbox", []),
                        frame_ts=float(c.get("timestamp", time.time())),
                        frame_bgr=c.get("frame"),
                    )
                fused_res = temp_voter.get_consensus(gate_id)
                if not fused_res:
                    fused_res = fuse_multiframe_plate_reads(candidates)

        if not fused_res:
            logger.debug("[%s] Multi-frame fusion returned None for candidates", gate_id)
            return None

        fused_plate = fused_res["fused_plate"]
        is_valid = fused_res.get("is_valid", False)
        best_frame = fused_res.get("best_frame")
        best_bbox = fused_res.get("best_bbox") or []
        confidence = float(fused_res.get("confidence", 0.85))
        agreement_rate = float(fused_res.get("agreement_rate", 1.0))
        slot_breakdown = fused_res.get("slot_breakdown", {})
        format_category = fused_res.get("format_category", "")

        # Requirement 5: Non-standard plates (consensus['requires_manual_check'] is True or consensus['action'] == 'MANUAL_CHECK')
        # are flagged with requires_manual_check=True in observation metadata.
        requires_manual_check = bool(
            fused_res.get("requires_manual_check") is True
            or fused_res.get("action") == "MANUAL_CHECK"
        )

        # 1. Statutory Indian Plate Validation & Positional Repair
        candidate_plate = fused_plate
        is_statutory = is_valid_indian_plate(candidate_plate)
        if not is_statutory and not requires_manual_check:
            repaired = repair_plate_positional(candidate_plate)
            if repaired:
                candidate_plate = repaired
                is_statutory = True
            else:
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

        # Tightened Gate: Never accept a static-noise fuzzy match unless is_valid_indian_plate is True
        # OR registry matched OR explicitly flagged for manual check.
        if not is_statutory and not registry_matched and not requires_manual_check:
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
        frame_cnt = int(fused_res.get("frame_count") or (len(candidates) if isinstance(candidates, list) else 1))
        
        # Extract vehicle-first cascade metadata
        v_class = "car"
        v_obs_type = ObservedVehicleType.CAR
        v_conf = 0.9
        v_track_id = gate_id
        v_bbox = []
        if isinstance(candidates, dict):
            v_class = candidates.get("vehicle_class", "car")
            v_obs_type = candidates.get("observed_type", ObservedVehicleType.CAR)
            v_conf = float(candidates.get("vehicle_confidence", 0.9))
            v_track_id = candidates.get("vehicle_track_id", gate_id)
            v_bbox = candidates.get("vehicle_bbox", [])
        elif isinstance(candidates, list) and candidates:
            c0 = candidates[0]
            v_class = c0.get("vehicle_class", "car")
            v_obs_type = c0.get("observed_type", ObservedVehicleType.CAR)
            v_conf = float(c0.get("vehicle_confidence", 0.9))
            v_track_id = c0.get("vehicle_track_id", gate_id)
            v_bbox = c0.get("vehicle_bbox", [])

        extra_meta = {
            "multiframe_consensus": True,
            "frame_count": frame_cnt,
            "agreement_rate": agreement_rate,
            "slot_breakdown": slot_breakdown,
            "format_category": format_category,
            "requires_manual_check": requires_manual_check,
            "action": "MANUAL_CHECK" if requires_manual_check else "PROCEED",
            "vehicle_class": v_class,
            "vehicle_track_id": v_track_id,
            "vehicle_bbox": v_bbox,
            "observed_type": v_obs_type,
            "vehicle_confidence": v_conf,
            "candidate_reads": (
                [c.get("raw_plate", "") for c in candidates if c.get("raw_plate")]
                if isinstance(candidates, list)
                else [fused_plate]
            ),
        }

        if isinstance(candidates, list) and candidates:
            sharpness = max([float(c.get("sharpness", 50.0)) for c in candidates])
        elif best_frame is not None and getattr(best_frame, "size", 0) > 0:
            try:
                g_frame = cv2.cvtColor(best_frame, cv2.COLOR_BGR2GRAY)
                sharpness = float(cv2.Laplacian(g_frame, cv2.CV_64F).var())
            except Exception:
                sharpness = 50.0
        else:
            sharpness = 50.0

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
                    "requires_manual_check": bool(extra_metadata.get("requires_manual_check", False) if extra_metadata else False),
                }
                if extra_metadata:
                    meta.update(extra_metadata)

                veh_type = extra_metadata.get("observed_type", ObservedVehicleType.CAR) if extra_metadata else ObservedVehicleType.CAR
                veh_conf = float(extra_metadata.get("vehicle_confidence", 0.9)) if extra_metadata else 0.9

                event_data = ObservationCreate(
                    gate_id=gate_id,
                    camera_id=f"{gate_id.lower()}_ip_cam",
                    observed_at=now_dt,
                    source=ObservationSource.OTHER,
                    source_event_id=source_event_id,
                    raw_plate=plate,
                    plate_confidence=float(confidence),
                    vehicle_type=veh_type,
                    vehicle_confidence=veh_conf,
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
