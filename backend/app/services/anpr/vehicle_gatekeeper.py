"""
Stage-0 Indian Vehicle Gatekeeper Service.
=========================================
Uses IISc AIM UVH-26 YOLOv11-S (or fallback YOLO11n) to detect approaching
vehicles at campus access gates before triggering plate detection and OCR.

Key Responsibilities:
1. Stage 0 Filtering: Fast early-exit on empty frames (zero vehicles -> return immediately,
   eliminating empty-space false positives and wasted OCR CPU).
2. Indian Class Mapping: Maps 14 IISc AIM classes cleanly into 5 unified vehicle categories:
   - 'two_wheeler': Two-wheeler, Bicycle
   - 'auto_rickshaw': Three-wheeler (auto-rickshaw, CNG)
   - 'car': Hatchback, Sedan, SUV, MUV, Van, Others
   - 'bus': Bus, Mini-bus, Tempo-traveller
   - 'truck': Truck, LCV
   (Pedestrians / non-vehicles are completely ignored).
3. Zoomed Vehicle Crop Extraction: Extracts vehicle crops with 5% padding so small
   2-wheeler and auto-rickshaw plates are magnified when passed to the plate detector.
4. Persistent Vehicle Tracking: Associates detections across frames with IoU tracking,
   maintaining persistent track_id and vehicle_class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from backend.app.config import BASE_DIR
from backend.app.models.enums import ObservedVehicleType

logger = logging.getLogger("campus_security.vehicle_gatekeeper")

ROOT_DIR = Path(BASE_DIR).resolve()
WEIGHTS_DIR = ROOT_DIR / "weights"

UVH26_MODEL_PATH = WEIGHTS_DIR / "uvh26_vehicle_yolo11s.onnx"
FALLBACK_MODEL_PATH = WEIGHTS_DIR / "yolo11n.onnx"

# IISc AIM UVH-26 14 Indian vehicle classes
UVH26_CLASS_NAMES: Dict[int, str] = {
    0: "Hatchback",
    1: "Sedan",
    2: "SUV",
    3: "MUV",
    4: "Bus",
    5: "Truck",
    6: "Three-wheeler",
    7: "Two-wheeler",
    8: "LCV",
    9: "Mini-bus",
    10: "Tempo-traveller",
    11: "Bicycle",
    12: "Van",
    13: "Others",
}

# Unified 5-class Indian vehicle mapping:
# 'two_wheeler', 'auto_rickshaw', 'car', 'bus', 'truck'
UVH26_TO_UNIFIED: Dict[int, str] = {
    0: "car",            # Hatchback
    1: "car",            # Sedan
    2: "car",            # SUV
    3: "car",            # MUV
    4: "bus",            # Bus
    5: "truck",          # Truck
    6: "auto_rickshaw",  # Three-wheeler
    7: "two_wheeler",    # Two-wheeler
    8: "truck",          # LCV (Light Commercial Vehicle)
    9: "bus",            # Mini-bus
    10: "bus",           # Tempo-traveller
    11: "two_wheeler",   # Bicycle
    12: "car",           # Van
    13: "car",           # Others
}

# COCO standard vehicle class mapping for fallback
COCO_VEHICLE_MAP: Dict[int, str] = {
    1: "two_wheeler",    # bicycle
    2: "car",            # car
    3: "two_wheeler",    # motorcycle
    5: "bus",            # bus
    7: "truck",          # truck
}

UNIFIED_TO_OBSERVED_TYPE: Dict[str, ObservedVehicleType] = {
    "two_wheeler": ObservedVehicleType.MOTORCYCLE,
    "auto_rickshaw": ObservedVehicleType.CAR,
    "car": ObservedVehicleType.CAR,
    "bus": ObservedVehicleType.BUS,
    "truck": ObservedVehicleType.TRUCK,
}


def compute_box_iou(boxA: List[int], boxB: List[int]) -> float:
    """Computes Intersection-over-Union between two boxes [x1, y1, x2, y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    interW = max(0, xB - xA)
    interH = max(0, yB - yA)
    interArea = interW * interH

    boxAArea = max(0, boxA[2] - boxA[0]) * max(0, boxA[3] - boxA[1])
    boxBArea = max(0, boxB[2] - boxB[0]) * max(0, boxB[3] - boxB[1])
    unionArea = float(boxAArea + boxBArea - interArea)

    if unionArea <= 0:
        return 0.0
    return float(interArea / unionArea)


@dataclass
class VehicleDetection:
    """Represents a detected vehicle in the frame."""
    bbox: List[int]  # [x1, y1, x2, y2] in original image coordinates
    confidence: float
    class_id: int
    class_name: str
    vehicle_class: str  # 'two_wheeler', 'auto_rickshaw', 'car', 'bus', 'truck'
    observed_type: ObservedVehicleType

    @property
    def width(self) -> int:
        return max(0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> int:
        return max(0, self.bbox[3] - self.bbox[1])

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class VehicleTrack:
    """Represents a persistent vehicle track across frames."""
    track_id: str
    vehicle_class: str
    observed_type: ObservedVehicleType
    bbox: List[int]
    confidence: float
    last_seen_ts: float
    first_seen_ts: float
    hits: int = 1

    @property
    def centroid(self) -> Tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2.0, (self.bbox[1] + self.bbox[3]) / 2.0)


class SimpleVehicleTracker:
    """
    Lightweight IoU + Centroid proximity tracker to assign persistent track_ids
    to vehicles across camera frames.
    """

    def __init__(self, gate_id: str = "GATE_1", max_age_sec: float = 2.0, iou_match_thresh: float = 0.20):
        self.gate_id = str(gate_id)
        self.max_age_sec = max_age_sec
        self.iou_match_thresh = iou_match_thresh
        self._next_id = 1
        self._tracks: Dict[str, VehicleTrack] = {}

    def update(self, detections: List[VehicleDetection], now_ts: Optional[float] = None) -> List[Tuple[VehicleTrack, VehicleDetection]]:
        ts = float(now_ts if now_ts is not None else time.time())

        # 1. Prune expired tracks
        stale = [tid for tid, trk in self._tracks.items() if (ts - trk.last_seen_ts) > self.max_age_sec]
        for tid in stale:
            del self._tracks[tid]

        matched: List[Tuple[VehicleTrack, VehicleDetection]] = []
        unmatched_dets = list(detections)

        # 2. Greedy match against existing tracks
        for tid, trk in list(self._tracks.items()):
            best_det = None
            best_iou = 0.0
            for det in unmatched_dets:
                iou = compute_box_iou(trk.bbox, det.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_det = det

            if best_det is not None and best_iou >= self.iou_match_thresh:
                trk.bbox = best_det.bbox
                trk.confidence = max(trk.confidence, best_det.confidence)
                trk.vehicle_class = best_det.vehicle_class
                trk.observed_type = best_det.observed_type
                trk.last_seen_ts = ts
                trk.hits += 1
                matched.append((trk, best_det))
                unmatched_dets.remove(best_det)

        # 3. Create new tracks for unmatched detections
        for det in unmatched_dets:
            tid = f"{self.gate_id}_veh_{self._next_id}"
            self._next_id += 1
            trk = VehicleTrack(
                track_id=tid,
                vehicle_class=det.vehicle_class,
                observed_type=det.observed_type,
                bbox=det.bbox,
                confidence=det.confidence,
                last_seen_ts=ts,
                first_seen_ts=ts,
                hits=1,
            )
            self._tracks[tid] = trk
            matched.append((trk, det))

        return matched

    def clear(self):
        self._tracks.clear()


def letterbox_for_yolo(image: np.ndarray, target_size: int = 640) -> Tuple[np.ndarray, float, int, int]:
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


class VehicleGatekeeper:
    """
    Stage-0 Indian Vehicle Detector & Gatekeeper.
    Filters frames before plate detection, assigns vehicle classes, and extracts zoomed crops.
    """

    def __init__(
        self,
        model_path: Optional[Path] = None,
        conf_thresh: float = 0.40,
        iou_thresh: float = 0.45,
        session: Optional[Any] = None,
    ):
        self.conf_thresh = float(conf_thresh)
        self.iou_thresh = float(iou_thresh)
        self.session = session
        self.is_uvh26 = True
        self.model_path = model_path

        if self.session is None:
            self._init_session(model_path)

    def _init_session(self, model_path: Optional[Path] = None):
        """Loads ONNX inference session."""
        target = model_path
        if target is None or not target.exists():
            if UVH26_MODEL_PATH.exists():
                target = UVH26_MODEL_PATH
                self.is_uvh26 = True
            elif FALLBACK_MODEL_PATH.exists():
                target = FALLBACK_MODEL_PATH
                self.is_uvh26 = False
            else:
                target = None

        self.model_path = target
        if target is not None and target.exists():
            try:
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self.session = ort.InferenceSession(str(target), opts, providers=["CPUExecutionProvider"])

                out_shape = self.session.get_outputs()[0].shape
                num_features = out_shape[1] if len(out_shape) > 1 and isinstance(out_shape[1], int) else 18
                if num_features == 18 or "uvh" in str(target).lower():
                    self.is_uvh26 = True
                else:
                    self.is_uvh26 = False
                logger.info("Loaded Vehicle Gatekeeper model from %s (UVH-26=%s)", target.name, self.is_uvh26)
            except Exception as e:
                logger.warning("Failed to initialize Vehicle Gatekeeper session from %s: %s", target, e)
                self.session = None
        else:
            logger.info("No Vehicle Gatekeeper ONNX weights found; running in passthrough mode.")
            self.session = None

    def detect_vehicles(self, frame: np.ndarray) -> List[VehicleDetection]:
        """
        Detects vehicles in the frame.
        Returns empty list if no vehicles are detected (indicating empty frame/wall/shadow).
        """
        if frame is None or frame.size == 0 or self.session is None:
            return []

        h, w = frame.shape[:2]
        if h < 50 or w < 50:
            return []

        # Letterbox padding
        canvas, scale, dx, dy = letterbox_for_yolo(frame, 640)
        canvas_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        inp = canvas_rgb.transpose(2, 0, 1)[np.newaxis, :, :, :].astype(np.float32) / 255.0

        try:
            inp_name = self.session.get_inputs()[0].name
            det_out = self.session.run(None, {inp_name: inp})[0][0]
        except Exception as e:
            logger.error("Vehicle Gatekeeper inference error: %s", e)
            return []

        if det_out.shape[0] < 5:
            return []

        num_classes = det_out.shape[0] - 4
        num_candidates = det_out.shape[1]

        boxes = []
        scores = []
        class_ids = []
        unified_classes = []

        class_map = UVH26_TO_UNIFIED if self.is_uvh26 else COCO_VEHICLE_MAP
        name_map = UVH26_CLASS_NAMES if self.is_uvh26 else {}

        for col in range(num_candidates):
            class_scores = det_out[4:, col]
            best_cls = int(np.argmax(class_scores))
            score = float(class_scores[best_cls])

            if score < self.conf_thresh:
                continue

            # Filter non-vehicles (e.g. pedestrians, animals)
            if best_cls not in class_map:
                continue

            unified_cls = class_map[best_cls]

            cx_pad, cy_pad, bw_pad, bh_pad = det_out[0:4, col]
            cx_orig = (cx_pad - dx) / scale
            cy_orig = (cy_pad - dy) / scale
            bw_orig = bw_pad / scale
            bh_orig = bh_pad / scale

            x1 = max(0, int(cx_orig - bw_orig / 2))
            y1 = max(0, int(cy_orig - bh_orig / 2))
            x2 = min(w, int(cx_orig + bw_orig / 2))
            y2 = min(h, int(cy_orig + bh_orig / 2))

            if (x2 - x1) < 20 or (y2 - y1) < 20:
                continue

            boxes.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(score)
            class_ids.append(best_cls)
            unified_classes.append(unified_cls)

        if not boxes:
            return []

        indices = cv2.dnn.NMSBoxes(boxes, scores, self.conf_thresh, self.iou_thresh)
        final_detections: List[VehicleDetection] = []

        for idx in (indices.flatten() if len(indices) > 0 else []):
            bx, by, bw, bh = boxes[idx]
            x1, y1, x2, y2 = bx, by, bx + bw, by + bh
            c_id = class_ids[idx]
            u_cls = unified_classes[idx]
            conf = scores[idx]
            c_name = name_map.get(c_id, u_cls)
            obs_type = UNIFIED_TO_OBSERVED_TYPE.get(u_cls, ObservedVehicleType.CAR)

            final_detections.append(
                VehicleDetection(
                    bbox=[x1, y1, x2, y2],
                    confidence=conf,
                    class_id=c_id,
                    class_name=c_name,
                    vehicle_class=u_cls,
                    observed_type=obs_type,
                )
            )

        return final_detections

    @staticmethod
    def crop_vehicle(
        frame: np.ndarray,
        bbox: List[int],
        pad_pct: float = 0.05,
    ) -> Tuple[np.ndarray, List[int]]:
        """
        Pads the vehicle bounding box by pad_pct (default 5%) and extracts crop.
        Returns (cropped_bgr, [pad_x1, pad_y1, pad_x2, pad_y2]).
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        bw = x2 - x1
        bh = y2 - y1

        pad_w = int(round(bw * pad_pct))
        pad_h = int(round(bh * pad_pct))

        px1 = max(0, x1 - pad_w)
        py1 = max(0, y1 - pad_h)
        px2 = min(w, x2 + pad_w)
        py2 = min(h, y2 + pad_h)

        crop = frame[py1:py2, px1:px2]
        return crop, [px1, py1, px2, py2]
