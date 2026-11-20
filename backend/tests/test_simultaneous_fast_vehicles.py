"""
Unit and Integration Tests for Simultaneous Multi-Vehicle & Fast-Moving Vehicle ANPR.
-----------------------------------------------------------------------------------
Verifies:
1. Simultaneous fast-moving vehicles (side-by-side / parallel lanes) maintain persistent
   tracks across frames without track switching, dropped tracks, or race conditions.
2. CameraStreamManager.process_frame processes and ingests ALL vehicles in a multi-plate
   frame (no premature exit on the first vehicle).
3. Fast-moving vehicles achieve early consensus on 2 consecutive matching statutory reads
   (allowing capture even when vehicle speeds through the gate in only 2-3 frames).
4. Departed fast vehicles with >= 2 frames are cleanly flushed and ingested by the idle worker
   without throwing TypeError or AttributeError.
5. TrackVoter implements list-like slicing, len, iteration, and track clearing.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from backend.app.models.enums import ObservedVehicleType
from backend.app.services.anpr.track_voter import TrackObservation, TrackVoter
from backend.app.services.anpr.vehicle_gatekeeper import (
    SimpleVehicleTracker,
    VehicleDetection,
    VehicleGatekeeper,
    VehicleTrack,
    compute_box_iou,
    compute_vehicle_association_score,
)
from backend.app.workers.camera_stream_runner import CameraStreamManager


def _create_synthetic_plate_image(
    text: str,
    bg_bgr: tuple[int, int, int] = (250, 250, 250),
    text_bgr: tuple[int, int, int] = (15, 15, 15),
    width: int = 240,
    height: int = 70,
) -> np.ndarray:
    """Creates a high-contrast synthetic plate image."""
    crop = np.full((height, width, 3), bg_bgr, dtype=np.uint8)
    cv2.rectangle(crop, (2, 2), (width - 3, height - 3), (30, 30, 30), 2)
    font_scale = 0.9
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    tx = max(10, (width - tw) // 2)
    ty = max(th + 10, (height + th) // 2)
    cv2.putText(crop, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_bgr, thickness)
    return crop


class TestSimultaneousFastVehicles:
    """Tests handling of multiple simultaneous vehicles moving at high speed."""

    def test_two_fast_cars_simultaneous_tracking(self):
        """
        Two cars travelling side-by-side at high speed (160px displacement per frame)
        must maintain persistent distinct track IDs without swapping or dropping.
        """
        tracker = SimpleVehicleTracker(gate_id="GATE_1", max_age_sec=2.0, iou_match_thresh=0.20)

        # Frame 1: Two cars side-by-side in left and right lanes
        detA1 = VehicleDetection(
            bbox=[100, 200, 400, 450],
            confidence=0.92,
            class_id=0,
            class_name="Hatchback",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        detB1 = VehicleDetection(
            bbox=[500, 180, 800, 430],
            confidence=0.91,
            class_id=1,
            class_name="Sedan",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        f1_matches = tracker.update([detA1, detB1], now_ts=100.0)
        assert len(f1_matches) == 2
        trk_ids_f1 = [trk.track_id for trk, _ in f1_matches]
        assert trk_ids_f1 == ["GATE_1_veh_1", "GATE_1_veh_2"]

        # Frame 2: Both cars move down 160 px due to speed (dt = 0.08s)
        detA2 = VehicleDetection(
            bbox=[105, 360, 405, 610],
            confidence=0.93,
            class_id=0,
            class_name="Hatchback",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        detB2 = VehicleDetection(
            bbox=[505, 340, 805, 590],
            confidence=0.90,
            class_id=1,
            class_name="Sedan",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        f2_matches = tracker.update([detA2, detB2], now_ts=100.08)
        assert len(f2_matches) == 2
        trk_map_f2 = {trk.track_id: trk for trk, _ in f2_matches}
        assert "GATE_1_veh_1" in trk_map_f2
        assert "GATE_1_veh_2" in trk_map_f2
        assert trk_map_f2["GATE_1_veh_1"].hits == 2
        assert trk_map_f2["GATE_1_veh_2"].hits == 2

        # Car 1 centroid must remain in the left lane (~255 px)
        assert trk_map_f2["GATE_1_veh_1"].centroid[0] < 350
        # Car 2 centroid must remain in the right lane (~655 px)
        assert trk_map_f2["GATE_1_veh_2"].centroid[0] > 450

        # Frame 3: Both cars move another 160 px down
        detA3 = VehicleDetection(
            bbox=[110, 520, 410, 770],
            confidence=0.94,
            class_id=0,
            class_name="Hatchback",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        detB3 = VehicleDetection(
            bbox=[510, 500, 810, 750],
            confidence=0.89,
            class_id=1,
            class_name="Sedan",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        f3_matches = tracker.update([detA3, detB3], now_ts=100.16)
        assert len(f3_matches) == 2
        trk_map_f3 = {trk.track_id: trk for trk, _ in f3_matches}
        assert trk_map_f3["GATE_1_veh_1"].hits == 3
        assert trk_map_f3["GATE_1_veh_2"].hits == 3

    def test_process_frame_captures_both_simultaneous_vehicles(self, monkeypatch):
        """
        When two cars are present in the same frame, process_frame must evaluate
        and ingest BOTH cars instead of prematurely exiting on the first car.
        """
        runner = CameraStreamManager(total_fps_budget=15.0)

        # Construct frame with 2 cars
        frame = np.full((720, 1280, 3), 160, dtype=np.uint8)
        cv2.putText(frame, "SIMULTANEOUS_CARS_TEST_SCENE", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 3)

        plateA = _create_synthetic_plate_image("DL3CQD3885", width=220, height=65)
        plateB = _create_synthetic_plate_image("HR01AZ3919", width=220, height=65)

        # Place car A on left, car B on right
        frame[350:415, 120:340] = plateA
        frame[350:415, 680:900] = plateB

        # Mock Gatekeeper to return 2 vehicle detections
        mock_gatekeeper = MagicMock()
        detA = VehicleDetection(
            bbox=[80, 200, 450, 600],
            confidence=0.92,
            class_id=0,
            class_name="Hatchback",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        detB = VehicleDetection(
            bbox=[620, 200, 990, 600],
            confidence=0.91,
            class_id=1,
            class_name="Sedan",
            vehicle_class="car",
            observed_type=ObservedVehicleType.CAR,
        )
        mock_gatekeeper.detect_vehicles.return_value = [detA, detB]
        mock_gatekeeper.session = MagicMock()
        runner._vehicle_gatekeeper = mock_gatekeeper

        # Mock Plate YOLO detector to detect plate inside each vehicle crop
        mock_det = MagicMock()
        def mock_det_run(output_names, input_feed):
            # Input is (1, 3, 640, 640)
            det_arr = np.zeros((1, 5, 1), dtype=np.float32)
            det_arr[0, 0, 0] = 320.0
            det_arr[0, 1, 0] = 320.0
            det_arr[0, 2, 0] = 220.0
            det_arr[0, 3, 0] = 65.0
            det_arr[0, 4, 0] = 0.92
            return [det_arr]

        mock_det.run.side_effect = mock_det_run
        mock_det.get_inputs.return_value = [MagicMock(name="images")]
        runner._det_session = mock_det

        # Mock dual-pass OCR to return distinct plates for each vehicle
        call_count = [0]
        def mock_dual_pass(crop, **kwargs):
            plate = "DL3CQD3885" if call_count[0] == 0 else "HR01AZ3919"
            call_count[0] += 1
            return (plate, 0.95, "cct_onnx")

        monkeypatch.setattr("backend.app.workers.camera_stream_runner.run_dual_pass_ocr", mock_dual_pass)

        # Intercept observation ingestion
        ingested_plates = []
        def intercept_ingest(**kwargs):
            plate = kwargs.get("plate")
            ingested_plates.append(plate)
            return plate

        monkeypatch.setattr(runner, "_ingest_observation", intercept_ingest)

        # Process frame without consensus requirement
        runner.process_frame("GATE_1", frame, require_consensus=False)

        # Both vehicle plate candidates must have been processed and passed to ingestion
        assert len(ingested_plates) == 2, f"Expected 2 ingested plates for 2 simultaneous cars, got {ingested_plates}"

    def test_fast_vehicle_early_consensus(self):
        """
        Fast-moving vehicle with 2 consecutive matching high-confidence statutory reads
        must achieve consensus immediately without waiting for 5 frames.
        """
        voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)

        # Frame 1: High confidence valid statutory read
        voter.add_observation(
            track_id="fast_veh_1",
            plate_text="DL3CQD3885",
            confidence=0.92,
            bbox=[100, 100, 300, 160],
            frame_ts=100.0,
        )
        assert voter.get_consensus("fast_veh_1", allow_fast_consensus=True) is None, "1 frame must not trigger consensus"

        # Frame 2: Identical statutory read with high confidence
        voter.add_observation(
            track_id="fast_veh_1",
            plate_text="DL3CQD3885",
            confidence=0.93,
            bbox=[100, 150, 300, 210],
            frame_ts=100.08,
        )
        consensus = voter.get_consensus("fast_veh_1", allow_fast_consensus=True)
        assert consensus is not None, "2 matching high-confidence statutory reads must grant fast-vehicle consensus"
        assert consensus["fused_plate"] == "DL3CQD3885"
        assert consensus["is_valid"] is True
        assert consensus["action"] == "PROCEED"

    def test_departed_fast_vehicle_idle_flush(self, monkeypatch):
        """
        A fast vehicle that exits the gate after 2 frames must be flushed and ingested
        by the idle worker check without throwing TypeError or AttributeError.
        """
        runner = CameraStreamManager(total_fps_budget=15.0)

        # Add 2 observations for a vehicle track
        tid = "GATE_1_veh_fast_departed"
        track_voter = runner._temporal_tracks[tid]
        track_voter.add_observation(
            track_id=tid,
            plate_text="RJ06C2985",
            confidence=0.91,
            bbox=[100, 200, 300, 260],
            frame_ts=100.0,
        )
        track_voter.add_observation(
            track_id=tid,
            plate_text="RJ06C2985",
            confidence=0.92,
            bbox=[100, 350, 300, 410],
            frame_ts=100.08,
        )
        runner._temporal_track_last_update[tid] = 100.08

        # TrackVoterList len must be 2
        assert len(track_voter) == 2

        flushed_ingests = []
        monkeypatch.setattr(runner, "_ingest_observation", lambda **kwargs: flushed_ingests.append(kwargs))

        # Simulate idle flush at now = 101.0 (idle = 0.92s > 0.7s)
        now = 101.0
        for track_id in list(runner._temporal_tracks.keys()):
            track = runner._temporal_tracks[track_id]
            obs_cnt = len(track)
            last_ts = runner._temporal_track_last_update.get(track_id, 0.0)
            idle_sec = now - last_ts
            gid = track_id.split("_veh_")[0] if "_veh_" in track_id else track_id

            if obs_cnt >= 2 and idle_sec >= 0.7:
                consensus = track.get_consensus(track_id)
                candidates = list(track[:8])
                track.clear_track(track_id)
                runner._temporal_track_last_update.pop(track_id, None)
                runner._fuse_and_ingest(gid, consensus if consensus else candidates)

        assert len(flushed_ingests) == 1
        assert flushed_ingests[0]["plate"] == "RJ06C2985"
        assert len(runner._temporal_tracks[tid]) == 0

    def test_track_voter_list_compatibility(self):
        """TrackVoter must support len(), indexing/slicing, clear(), and iteration."""
        v = TrackVoter(min_consensus_frames=3, max_track_frames=8)
        assert len(v) == 0

        v.add_observation("t1", "MH04CN2300", 0.90, [10, 10, 100, 50], 1.0)
        v.add_observation("t1", "MH04CN2300", 0.92, [10, 20, 100, 60], 2.0)
        assert len(v) == 2

        # Slicing
        cands = list(v[:2])
        assert len(cands) == 2
        assert cands[0]["raw_plate"] == "MH04CN2300"
        assert cands[0]["conf"] == 0.90

        # Iteration
        all_obs = [obs["raw_plate"] for obs in v]
        assert all_obs == ["MH04CN2300", "MH04CN2300"]

        # Clear
        v.clear()
        assert len(v) == 0
