"""
Unit and Integration Tests for Stage-0 Indian Vehicle Gatekeeper (UVH-26 YOLOv11-S)
and Vehicle-First ANPR Cascade in CameraStreamManager.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from backend.app.models.enums import ObservedVehicleType
from backend.app.services.anpr.vehicle_gatekeeper import (
    FALLBACK_MODEL_PATH,
    SimpleVehicleTracker,
    UVH26_CLASS_NAMES,
    UVH26_MODEL_PATH,
    UVH26_TO_UNIFIED,
    VehicleDetection,
    VehicleGatekeeper,
    VehicleTrack,
    compute_box_iou,
)
from backend.app.workers.camera_stream_runner import CameraStreamManager


def _create_synthetic_plate(
    text: str = "CH01AB1234",
    bg_bgr: tuple[int, int, int] = (245, 245, 245),
    text_bgr: tuple[int, int, int] = (15, 15, 15),
    width: int = 240,
    height: int = 70,
) -> np.ndarray:
    """Creates a high-contrast synthetic plate image with valid aspect ratio."""
    crop = np.full((height, width, 3), bg_bgr, dtype=np.uint8)
    cv2.rectangle(crop, (2, 2), (width - 3, height - 3), (40, 40, 40), 2)
    font_scale = 0.9
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    tx = max(10, (width - tw) // 2)
    ty = max(th + 10, (height + th) // 2)
    cv2.putText(crop, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_bgr, thickness)
    return crop


class TestVehicleGatekeeperClassesAndTracking:
    """Verifies class mappings, IoU computation, and multi-frame tracking."""

    def test_uvh26_14_classes_mapping(self):
        """All 14 IISc AIM classes must map cleanly into the 5 unified classes."""
        expected_classes = {"two_wheeler", "auto_rickshaw", "car", "bus", "truck"}
        assert len(UVH26_CLASS_NAMES) == 14
        assert len(UVH26_TO_UNIFIED) == 14

        for cid, cname in UVH26_CLASS_NAMES.items():
            unified = UVH26_TO_UNIFIED[cid]
            assert unified in expected_classes, f"Class {cid} ({cname}) mapped to unknown class {unified}"

        # Check key specific Indian vehicle categories
        assert UVH26_TO_UNIFIED[6] == "auto_rickshaw"  # Three-wheeler
        assert UVH26_TO_UNIFIED[7] == "two_wheeler"    # Two-wheeler
        assert UVH26_TO_UNIFIED[4] == "bus"            # Bus
        assert UVH26_TO_UNIFIED[5] == "truck"          # Truck
        assert UVH26_TO_UNIFIED[8] == "truck"          # LCV
        assert UVH26_TO_UNIFIED[0] == "car"            # Hatchback

    def test_box_iou_computation(self):
        """Verifies IoU computation on overlapping and disjoint boxes."""
        boxA = [100, 100, 200, 200]
        boxB = [100, 100, 200, 200]
        assert compute_box_iou(boxA, boxB) == pytest.approx(1.0)

        boxC = [150, 100, 250, 200]  # 50% overlap horizontally
        iou = compute_box_iou(boxA, boxC)
        assert 0.30 < iou < 0.40

        boxD = [300, 300, 400, 400]  # Disjoint
        assert compute_box_iou(boxA, boxD) == 0.0

    def test_simple_vehicle_tracker_lifecycle(self):
        """Verifies persistent track allocation, association, and pruning."""
        tracker = SimpleVehicleTracker(gate_id="GATE_1", max_age_sec=1.5, iou_match_thresh=0.25)

        t0 = 1000.0
        # Frame 1: Car detected at [100, 100, 400, 300]
        det1 = VehicleDetection(
            bbox=[100, 100, 400, 300],
            confidence=0.88,
            class_id=0,
            class_name="Hatchback",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        matched1 = tracker.update([det1], now_ts=t0)
        assert len(matched1) == 1
        track1, _ = matched1[0]
        assert track1.track_id == "GATE_1_veh_1"
        assert track1.vehicle_class == "car"
        assert track1.hits == 1

        # Frame 2 (0.1s later): Vehicle moved slightly to [110, 105, 410, 305]
        t1 = t0 + 0.1
        det2 = VehicleDetection(
            bbox=[110, 105, 410, 305],
            confidence=0.91,
            class_id=0,
            class_name="Hatchback",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        # Also new 2-wheeler appears at [500, 200, 650, 450]
        det_2w = VehicleDetection(
            bbox=[500, 200, 650, 450],
            confidence=0.85,
            class_id=7,
            class_name="Two-wheeler",
            vehicle_class="two_wheeler",
            observed_type=ObservedVehicleType.MOTORCYCLE,
        )
        matched2 = tracker.update([det2, det_2w], now_ts=t1)
        assert len(matched2) == 2

        track_ids = {t.track_id for t, _ in matched2}
        assert "GATE_1_veh_1" in track_ids
        assert "GATE_1_veh_2" in track_ids

        # Frame 3 (0.3s later): veh_2 updated, veh_1 not present
        t2 = t1 + 0.3
        det_2w_moved = VehicleDetection(
            bbox=[510, 205, 660, 455],
            confidence=0.89,
            class_id=7,
            class_name="Two-wheeler",
            vehicle_class="two_wheeler",
            observed_type=ObservedVehicleType.MOTORCYCLE,
        )
        matched3 = tracker.update([det_2w_moved], now_ts=t2)
        assert len(matched3) == 1
        assert matched3[0][0].track_id == "GATE_1_veh_2"

        # Frame 4 (1.8s after t1): veh_1 (last seen at t1, 1.8s > 1.5s max_age) is pruned
        t3 = t1 + 1.8
        det_2w_still = VehicleDetection(
            bbox=[512, 207, 662, 457],
            confidence=0.90,
            class_id=7,
            class_name="Two-wheeler",
            vehicle_class="two_wheeler",
            observed_type=ObservedVehicleType.MOTORCYCLE,
        )
        matched4 = tracker.update([det_2w_still], now_ts=t3)
        assert len(matched4) == 1
        assert matched4[0][0].track_id == "GATE_1_veh_2"
        assert "GATE_1_veh_1" not in tracker._tracks


class TestStage0VehicleGatekeeperCascade:
    """Verifies Stage 0 early exit and Stage 1 zoomed plate detection inside vehicle crops."""

    def test_stage0_empty_frame_early_exit(self):
        """
        Requirement (a): Empty frames (bare walls, empty space, zero vehicles detected)
        MUST exit at Stage 0 immediately WITHOUT invoking Plate YOLO or OCR.
        """
        runner = CameraStreamManager(total_fps_budget=15.0)

        # Mock Gatekeeper that detects 0 vehicles
        mock_gatekeeper = MagicMock()
        mock_gatekeeper.session = MagicMock()
        mock_gatekeeper.detect_vehicles.return_value = []
        runner._vehicle_gatekeeper = mock_gatekeeper

        # Mock Plate YOLO detector and OCR sessions
        mock_det = MagicMock()
        mock_ocr = MagicMock()
        mock_rapid = MagicMock()
        runner._det_session = mock_det
        runner._ocr_session = mock_ocr
        runner._rapid_ocr = mock_rapid

        # Construct high-sharpness frame with textured wall / empty background (no vehicle)
        empty_frame = np.full((720, 1280, 3), 160, dtype=np.uint8)
        cv2.putText(empty_frame, "EMPTY_CAMPUS_GATE_EMPTY_WALL", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 3)

        # Process frame
        res = runner.process_frame("GATE_1", empty_frame, require_consensus=False)

        # Assert Stage 0 early exit
        assert res is None, "Empty frame must return None at Stage 0"
        mock_gatekeeper.detect_vehicles.assert_called_once()
        mock_det.run.assert_not_called(), "Plate YOLO must NEVER be called when 0 vehicles are detected!"
        mock_ocr.run.assert_not_called(), "CRNN OCR must NEVER be called when 0 vehicles are detected!"
        mock_rapid.assert_not_called()

    def test_stage1_vehicle_crop_zooming_two_wheeler_and_auto(self, monkeypatch):
        """
        Requirement (b): Zoomed vehicle crop detection detects a small 2-wheeler/auto
        plate and correctly tags vehicle_class and vehicle_type.
        """
        runner = CameraStreamManager(total_fps_budget=15.0)

        # 1280x720 frame with high sharpness
        frame = np.full((720, 1280, 3), 180, dtype=np.uint8)
        cv2.putText(frame, "GATE_1_LIVE_FEED", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 2)

        # Embed an auto-rickshaw at [x1=200, y1=150, x2=550, y2=600] (w=350, h=450)
        auto_bbox = [200, 150, 550, 600]
        # Inside the auto-rickshaw, embed a small plate at relative coords (e.g. [80, 360, 260, 420])
        # In full frame: x1 = 200 + 80 = 280, y1 = 150 + 360 = 510, x2 = 460, y2 = 570 (w=180, h=60, AR=3.0)
        plate_crop = _create_synthetic_plate(
            text="CH01AB1234",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=180,
            height=60,
        )
        frame[510:570, 280:460] = plate_crop

        # Mock Gatekeeper detecting this auto_rickshaw
        mock_gatekeeper = MagicMock()
        mock_gatekeeper.session = MagicMock()
        auto_det = VehicleDetection(
            bbox=auto_bbox,
            confidence=0.92,
            class_id=6,
            class_name="Three-wheeler",
            vehicle_class="auto_rickshaw",
            observed_type=ObservedVehicleType.CAR,
        )
        mock_gatekeeper.detect_vehicles.return_value = [auto_det]
        mock_gatekeeper.crop_vehicle = VehicleGatekeeper.crop_vehicle
        runner._vehicle_gatekeeper = mock_gatekeeper

        # Vehicle crop will be auto_bbox padded by 5%:
        # w=350 -> pad_w=18; h=450 -> pad_h=23
        # px1=182, py1=127, px2=568, py2=623
        # Plate inside crop: local_x1 = 280 - 182 = 98, local_y1 = 510 - 127 = 383, w=180, h=60
        # Mock Plate YOLO detector on this vehicle crop (640x640 letterbox)
        v_crop_w = 568 - 182  # 386
        v_crop_h = 623 - 127  # 496
        scale = 640.0 / 496.0  # ~1.2903
        dx = int((640 - 386 * scale) // 2)
        dy = 0

        plate_cx_crop = 98 + 90   # 188
        plate_cy_crop = 383 + 30  # 413
        plate_bw_crop = 180
        plate_bh_crop = 60

        cx_pad = plate_cx_crop * scale + dx
        cy_pad = plate_cy_crop * scale + dy
        bw_pad = plate_bw_crop * scale
        bh_pad = plate_bh_crop * scale

        det_out = np.zeros((5, 1), dtype=np.float32)
        det_out[0, 0] = cx_pad
        det_out[1, 0] = cy_pad
        det_out[2, 0] = bw_pad
        det_out[3, 0] = bh_pad
        det_out[4, 0] = 0.89  # Plate confidence score

        mock_det = MagicMock()
        mock_det.run.return_value = [det_out[np.newaxis, :, :]]
        mock_det.get_inputs.return_value = [MagicMock(name="images")]
        runner._det_session = mock_det

        # Mock CRNN session returning CH01AB1234
        mock_ocr = MagicMock()
        mock_ocr.run.return_value = ("CH01AB1234", 0.96)
        runner._ocr_session = mock_ocr

        # Intercept _ingest_observation to inspect metadata
        ingested_records = []
        def intercept_ingest(**kwargs):
            ingested_records.append(kwargs)
            return kwargs.get("plate")

        monkeypatch.setattr(runner, "_ingest_observation", intercept_ingest)

        # Process frame
        res = runner.process_frame("GATE_1", frame, require_consensus=False)

        assert res == "CH01AB1234", f"Expected plate 'CH01AB1234', got '{res}'"
        assert len(ingested_records) == 1
        meta = ingested_records[0].get("extra_metadata", {})
        assert meta.get("vehicle_class") == "auto_rickshaw", f"Expected 'auto_rickshaw', got {meta.get('vehicle_class')}"
        assert meta.get("vehicle_bbox") == auto_bbox
        assert "GATE_1_veh_" in meta.get("vehicle_track_id", "")
        assert meta.get("observed_type") == ObservedVehicleType.CAR

    def test_stage1_vehicle_crop_zooming_two_wheeler_motorcycle(self, monkeypatch):
        """Verifies two_wheeler detection correctly tags ObservedVehicleType.MOTORCYCLE."""
        runner = CameraStreamManager(total_fps_budget=15.0)

        frame = np.full((720, 1280, 3), 180, dtype=np.uint8)
        cv2.putText(frame, "GATE_2_2W_TEST", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 2)

        # Motorcycle box
        motorcycle_bbox = [400, 200, 650, 650]
        plate_crop = _create_synthetic_plate(
            text="PB65BB5678",
            bg_bgr=(250, 250, 250),
            text_bgr=(10, 10, 10),
            width=140,
            height=70,  # 2.0 AR (typical 2W plate)
        )
        frame[550:620, 450:590] = plate_crop

        mock_gatekeeper = MagicMock()
        mock_gatekeeper.session = MagicMock()
        moto_det = VehicleDetection(
            bbox=motorcycle_bbox,
            confidence=0.94,
            class_id=7,
            class_name="Two-wheeler",
            vehicle_class="two_wheeler",
            observed_type=ObservedVehicleType.MOTORCYCLE,
        )
        mock_gatekeeper.detect_vehicles.return_value = [moto_det]
        mock_gatekeeper.crop_vehicle = VehicleGatekeeper.crop_vehicle
        runner._vehicle_gatekeeper = mock_gatekeeper

        # Mock plate detection inside crop
        det_out = np.zeros((5, 1), dtype=np.float32)
        det_out[0, 0] = 320.0
        det_out[1, 0] = 520.0
        det_out[2, 0] = 140.0
        det_out[3, 0] = 70.0
        det_out[4, 0] = 0.91

        mock_det = MagicMock()
        mock_det.run.return_value = [det_out[np.newaxis, :, :]]
        mock_det.get_inputs.return_value = [MagicMock(name="images")]
        runner._det_session = mock_det

        mock_ocr = MagicMock()
        mock_ocr.run.side_effect = [("PB65", 0.95), ("BB5678", 0.95), ("PB65", 0.95), ("BB5678", 0.95)]
        runner._ocr_session = mock_ocr

        ingested = []
        monkeypatch.setattr(runner, "_ingest_observation", lambda **kwargs: ingested.append(kwargs))

        res = runner.process_frame("GATE_2", frame, require_consensus=False)
        assert res == "PB65BB5678"
        assert len(ingested) == 1
        meta = ingested[0]["extra_metadata"]
        assert meta["vehicle_class"] == "two_wheeler"
        assert meta["observed_type"] == ObservedVehicleType.MOTORCYCLE

    def test_real_uvh26_onnx_model_loading_and_inference(self):
        """Verifies real UVH-26 ONNX model loads from disk and runs inference cleanly."""
        assert UVH26_MODEL_PATH.exists(), f"UVH-26 ONNX model must exist at {UVH26_MODEL_PATH}"
        gk = VehicleGatekeeper(model_path=UVH26_MODEL_PATH)
        assert gk.session is not None
        assert gk.is_uvh26 is True

        # Test on black frame
        black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        dets = gk.detect_vehicles(black_frame)
        assert len(dets) == 0

        # Test padding crop
        crop, pad_box = gk.crop_vehicle(black_frame, [100, 100, 300, 400], pad_pct=0.05)
        assert pad_box == [90, 85, 310, 415]
        assert crop.shape == (330, 220, 3)
