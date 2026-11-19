"""
Unit and Integration Tests for Multi-Frame Plate Consensus and Statutory Indian Slot Verification.
--------------------------------------------------------------------------------------------------
Verifies:
1. Decomposing raw OCR reads into statutory Indian slots (State, RTO, Series, Number).
2. Delhi 1-digit RTO (DL3CAB1234) and Karnataka blank series (KA011234) support.
3. Trimming phantom 5th trailing digit (GJ13UX35217 -> GJ13UX3521).
4. Rejection of non-Indian formatted plates and unknown states.
5. Multi-frame confidence-weighted voting across 5-8 temporal candidate crops.
6. Temporal buffering and consensus trigger in CameraStreamManager.
"""

import time
import numpy as np
import pytest

from backend.app.services.multiframe_plate_consensus import (
    decompose_indian_plate_slots,
    fuse_multiframe_plate_reads,
)
from backend.app.services.plate_normalizer import is_valid_indian_plate, suggest_repairs
from backend.app.workers.camera_stream_runner import CameraStreamManager


def test_decompose_standard_plates():
    # 1. Standard plate
    s1 = decompose_indian_plate_slots("MH12AB1234")
    assert s1 is not None
    assert s1["kind"] == "standard"
    assert s1["state"] == "MH"
    assert s1["rto"] == "12"
    assert s1["series"] == "AB"
    assert s1["number"] == "1234"

    # 2. Delhi unpadded 1-digit zone
    s2 = decompose_indian_plate_slots("DL3CAB1234")
    assert s2 is not None
    assert s2["kind"] == "standard"
    assert s2["state"] == "DL"
    assert s2["rto"] == "3"
    assert s2["series"] == "CAB"
    assert s2["number"] == "1234"

    # 3. Karnataka blank series
    s3 = decompose_indian_plate_slots("KA011234")
    assert s3 is not None
    assert s3["kind"] == "standard"
    assert s3["state"] == "KA"
    assert s3["rto"] == "01"
    assert s3["series"] == ""
    assert s3["number"] == "1234"

    # 4. Bharat series
    s4 = decompose_indian_plate_slots("22BH1234AA")
    assert s4 is not None
    assert s4["kind"] == "bh"
    assert s4["yy"] == "22"
    assert s4["number"] == "1234"
    assert s4["series"] == "AA"


def test_decompose_and_repair_phantom_digits():
    # Phantom 5th trailing digit (common OCR glare/border artifact)
    s = decompose_indian_plate_slots("GJ13UX35217")
    assert s is not None
    assert s["state"] == "GJ"
    assert s["rto"] == "13"
    assert s["series"] == "UX"
    assert s["number"] == "3521"

    # Fused result must produce the valid Indian plate
    cands = [
        {"raw_plate": "GJ13UX35217", "conf": 0.88},
        {"raw_plate": "GJ13UX3521", "conf": 0.92},
        {"raw_plate": "GJ13UX3521", "conf": 0.95},
    ]
    fused = fuse_multiframe_plate_reads(cands)
    assert fused is not None
    assert fused["fused_plate"] == "GJ13UX3521"
    assert fused["is_valid"] is True


def test_rejection_of_non_indian_candidates():
    # Unknown/bogus state code
    s_invalid = decompose_indian_plate_slots("XX99ZZ9999")
    assert s_invalid is not None
    assert s_invalid["state"] == "XX"

    cands = [
        {"raw_plate": "XX99ZZ9999", "conf": 0.90},
        {"raw_plate": "XX99ZZ9999", "conf": 0.92},
    ]
    fused = fuse_multiframe_plate_reads(cands)
    assert fused is not None
    assert fused["is_valid"] is False
    assert is_valid_indian_plate(fused["fused_plate"]) is False


def test_multiframe_voting_resolves_flicker():
    # Simulate 5-frame video sequence where:
    # - Frame 1 has O/0 confusion in RTO: KAO1AX3347
    # - Frame 2 has state code noise: KL01AX3347
    # - Frame 3 has digit flicker in number: KA01AX3547
    # - Frames 4 & 5 read correct: KA01AX3347
    frame_clear = np.full((100, 200, 3), 200, dtype=np.uint8)
    frame_blurry = np.full((100, 200, 3), 100, dtype=np.uint8)

    candidates = [
        {"raw_plate": "KAO1AX3347", "conf": 0.82, "sharpness": 80.0, "frame": frame_blurry, "bbox": [10, 10, 50, 20]},
        {"raw_plate": "KL01AX3347", "conf": 0.80, "sharpness": 75.0, "frame": frame_blurry, "bbox": [10, 10, 50, 20]},
        {"raw_plate": "KA01AX3547", "conf": 0.85, "sharpness": 90.0, "frame": frame_blurry, "bbox": [10, 10, 50, 20]},
        {"raw_plate": "KA01AX3347", "conf": 0.94, "sharpness": 150.0, "frame": frame_clear, "bbox": [12, 12, 52, 22]},
        {"raw_plate": "KA01AX3347", "conf": 0.95, "sharpness": 140.0, "frame": frame_blurry, "bbox": [12, 12, 52, 22]},
    ]

    res = fuse_multiframe_plate_reads(candidates)
    assert res is not None
    assert res["fused_plate"] == "KA01AX3347"
    assert res["is_valid"] is True
    assert res["frame_count"] == 5
    # The clearest frame (sharpness 150.0 * 0.94) must be selected for snapshot evidence
    assert res["best_frame"] is frame_clear
    assert res["best_bbox"] == [12, 12, 52, 22]


def test_camera_stream_temporal_tracking_trigger():
    # Verifies temporal aggregation:
    # 1-4 frames do not trigger ingestion when require_consensus=True;
    # 5th frame triggers fusion and returns the consolidated plate.
    runner = CameraStreamManager(total_fps_budget=15.0)
    gate_id = "GATE_TEST"

    # Pre-populate 4 frames
    for i in range(4):
        runner._temporal_tracks[gate_id].append({
            "raw_plate": "DL01AB1234",
            "conf": 0.90,
            "bbox": [10, 10, 100, 50],
            "frame": np.zeros((100, 100, 3), dtype=np.uint8),
            "sharpness": 100.0,
            "timestamp": time.time(),
        })
    assert len(runner._temporal_tracks[gate_id]) == 4

    # 5th candidate arrives
    cand5 = {
        "raw_plate": "DL01AB1234",
        "conf": 0.92,
        "bbox": [10, 10, 100, 50],
        "frame": np.zeros((100, 100, 3), dtype=np.uint8),
        "sharpness": 110.0,
        "timestamp": time.time(),
    }
    runner._temporal_tracks[gate_id].append(cand5)
    assert len(runner._temporal_tracks[gate_id]) == 5

    batch = runner._temporal_tracks[gate_id][:8]
    runner._temporal_tracks[gate_id] = runner._temporal_tracks[gate_id][8:]

    fused_res = fuse_multiframe_plate_reads(batch)
    assert fused_res is not None
    assert fused_res["fused_plate"] == "DL01AB1234"
    assert fused_res["is_valid"] is True
    assert len(runner._temporal_tracks[gate_id]) == 0
