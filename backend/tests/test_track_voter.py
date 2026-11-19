"""
Unit and Integration Tests for CMVR Rule 50 Positional Grammar & Track Voting.
-------------------------------------------------------------------------------
Verifies:
1. Positional correction on corrupted reads (P810A81234 -> PB10AB1234,
   0L01AB1234 -> DL01AB1234, 228H1234AA -> 22BH1234AA).
2. Statutory Indian plate classification ('STANDARD', 'BHARAT_SERIES',
   'VINTAGE', 'DIPLOMATIC', 'MILITARY', 'INVALID').
3. Stripping of leading 'IND' artifacts and non-alphanumeric noise.
4. Delhi 1-digit RTO and Karnataka blank series support in repair.
5. Multi-frame confidence-weighted positional voting across jittery reads.
6. Routing of non-standard plates (military, diplomatic, temporary, invalid)
   to MANUAL_CHECK.
7. Track lifecycle: min_consensus_frames threshold, sliding window, and clear_track.
"""

import numpy as np
import pytest

from backend.app.services.anpr.track_voter import TrackVoter
from backend.app.services.plate_normalizer import (
    classify_plate_format,
    correct_indian_plate,
    is_valid_indian_plate,
    normalize_plate,
    repair_plate_positional,
    suggest_repairs,
)


# =============================================================================
# 1. Positional Grammar & Statutory Repair (correct_indian_plate)
# =============================================================================

def test_correct_indian_plate_corrupted_reads():
    """Verifies positional OCR confusion repairs for statutory plates."""
    # State & series confusion: 8 in letter slot -> B
    plate, conf, fmt = correct_indian_plate("P810A81234")
    assert plate == "PB10AB1234"
    assert fmt == "STANDARD"
    assert conf >= 0.70

    # State confusion: 0 in letter slot -> D (DL is valid, OL is not)
    plate, conf, fmt = correct_indian_plate("0L01AB1234")
    assert plate == "DL01AB1234"
    assert fmt == "STANDARD"
    assert conf >= 0.85

    # Bharat series: 8H in BH slot -> BH
    plate, conf, fmt = correct_indian_plate("228H1234AA")
    assert plate == "22BH1234AA"
    assert fmt == "BHARAT_SERIES"
    assert conf >= 0.85

    # Bharat series: B4 in BH slot -> BH
    plate, conf, fmt = correct_indian_plate("22B41234AA")
    assert plate == "22BH1234AA"
    assert fmt == "BHARAT_SERIES"
    assert conf >= 0.85


def test_correct_indian_plate_clean_statutory_formats():
    """Verifies that already valid plates are correctly categorized with 1.0 confidence."""
    # Standard format
    p, c, f = correct_indian_plate("MH12DE1433")
    assert p == "MH12DE1433"
    assert f == "STANDARD"
    assert c == 1.0

    # Bharat series
    p, c, f = correct_indian_plate("22BH1234AA")
    assert p == "22BH1234AA"
    assert f == "BHARAT_SERIES"
    assert c == 1.0

    # Vintage plate
    p, c, f = correct_indian_plate("DLVAAB1234")
    assert p == "DLVAAB1234"
    assert f == "VINTAGE"
    assert c == 1.0

    # Diplomatic plate
    p, c, f = correct_indian_plate("77CD1234")
    assert p == "77CD1234"
    assert f == "DIPLOMATIC"
    assert c == 1.0

    # Military plate
    p, c, f = correct_indian_plate("22D123456A")
    assert p == "22D123456A"
    assert f == "MILITARY"
    assert c == 1.0


def test_correct_indian_plate_delhi_and_karnataka_exceptions():
    """Verifies Delhi 1-digit RTO and Karnataka blank series handling."""
    # Delhi 1-digit RTO (valid)
    p, c, f = correct_indian_plate("DL3CAB1234")
    assert p == "DL3CAB1234"
    assert f == "STANDARD"
    assert c == 1.0

    # Delhi 1-digit RTO with letter confusion (0L -> DL)
    p, c, f = correct_indian_plate("0L3CAB1234")
    assert p == "DL3CAB1234"
    assert f == "STANDARD"
    assert c >= 0.85

    # Karnataka blank series (valid)
    p, c, f = correct_indian_plate("KA011234")
    assert p == "KA011234"
    assert f == "STANDARD"
    assert c == 1.0

    # Karnataka blank series with O->0 confusion in RTO
    p, c, f = correct_indian_plate("KAO11234")
    assert p == "KA011234"
    assert f == "STANDARD"
    assert c >= 0.85


def test_correct_indian_plate_strips_ind_artifacts():
    """Verifies leading 'IND' artifacts and non-alphanumeric noise are stripped."""
    # Leading IND with space
    p, c, f = correct_indian_plate("IND DL01AB1234")
    assert p == "DL01AB1234"
    assert f == "STANDARD"
    assert c == 1.0

    # Leading IND with hyphen
    p, c, f = correct_indian_plate("IND-22BH1234AA")
    assert p == "22BH1234AA"
    assert f == "BHARAT_SERIES"
    assert c == 1.0

    # Leading IND on corrupted plate
    p, c, f = correct_indian_plate("IND P810A81234")
    assert p == "PB10AB1234"
    assert f == "STANDARD"
    assert c >= 0.70

    # Leading 1ND (common OCR misread of IND)
    p, c, f = correct_indian_plate("1ND-0L01AB1234")
    assert p == "DL01AB1234"
    assert f == "STANDARD"


def test_correct_indian_plate_phantom_fifth_digit():
    """Verifies trimming of phantom 5th trailing digit from border glare/reflection."""
    p, c, f = correct_indian_plate("GJ13UX35217")
    assert p == "GJ13UX3521"
    assert f == "STANDARD"
    assert c >= 0.85


def test_correct_indian_plate_invalid_and_empty():
    """Verifies that unrepairable noise and empty inputs yield INVALID."""
    p, c, f = correct_indian_plate("")
    assert p == ""
    assert f == "INVALID"
    assert c == 0.0

    p, c, f = correct_indian_plate("   ")
    assert p == ""
    assert f == "INVALID"
    assert c == 0.0

    p, c, f = correct_indian_plate("XX99ZZ9999")
    assert p == "XX99ZZ9999"
    assert f == "INVALID"
    assert c == 0.0

    p, c, f = correct_indian_plate("EMPTYWALL")
    assert p == "EMPTYWALL"
    assert f == "INVALID"
    assert c == 0.0


# =============================================================================
# 2. Multi-Frame Track Voting (TrackVoter)
# =============================================================================

def test_track_voter_multi_frame_positional_jitter():
    """
    Simulates a 5-frame vehicle track where each frame has jitter at different positions.
    Confidence-weighted voting should reconstruct the true statutory plate.
    """
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_jitter_01"

    frame_reads = [
        ("P810AB1234", 0.75),  # 8 at position 1 (state)
        ("PB10A81234", 0.78),  # 8 at position 5 (series)
        ("PB10AB1234", 0.92),  # clean
        ("P810AB1234", 0.80),  # 8 at position 1
        ("PB10AB1234", 0.95),  # clean
    ]

    for idx, (txt, conf) in enumerate(frame_reads):
        voter.add_observation(
            track_id=track_id,
            plate_text=txt,
            confidence=conf,
            bbox=[10, 10, 100, 50],
            frame_ts=100.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["fused_plate"] == "PB10AB1234"
    assert consensus["format_category"] == "STANDARD"
    assert consensus["requires_manual_check"] is False
    assert consensus["action"] == "PROCEED"
    assert consensus["frame_count"] == 5
    assert consensus["agreement_rate"] == 1.0  # all frames resolve/repair to PB10AB1234


def test_track_voter_bharat_series_jitter():
    """Verifies track voting on Bharat series with OCR confusions across frames."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_bh_01"

    frame_reads = [
        ("228H1234AA", 0.82),
        ("22BH1234AA", 0.90),
        ("22B41234AA", 0.76),
        ("22BH1234AA", 0.95),
        ("22BH1234AA", 0.94),
    ]

    for idx, (txt, conf) in enumerate(frame_reads):
        voter.add_observation(
            track_id=track_id,
            plate_text=txt,
            confidence=conf,
            bbox=[10, 10, 100, 50],
            frame_ts=100.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["fused_plate"] == "22BH1234AA"
    assert consensus["format_category"] == "BHARAT_SERIES"
    assert consensus["requires_manual_check"] is False
    assert consensus["action"] == "PROCEED"


def test_track_voter_all_corrupted_reads_repaired():
    """
    Even if every frame read suffered the same OCR corruption,
    positional repair in consensus must output the statutory plate.
    """
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_all_corrupted"

    for idx in range(5):
        voter.add_observation(
            track_id=track_id,
            plate_text="0L01AB1234",  # 0 instead of D
            confidence=0.88,
            bbox=[10, 10, 100, 50],
            frame_ts=10.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["fused_plate"] == "DL01AB1234"
    assert consensus["format_category"] == "STANDARD"
    assert consensus["requires_manual_check"] is False
    assert consensus["action"] == "PROCEED"


def test_track_voter_military_routes_to_manual_check():
    """Non-standard military plate format must set requires_manual_check=True."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_military"

    for idx in range(5):
        voter.add_observation(
            track_id=track_id,
            plate_text="22D123456A",
            confidence=0.92,
            bbox=[10, 10, 100, 50],
            frame_ts=10.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["fused_plate"] == "22D123456A"
    assert consensus["format_category"] == "MILITARY"
    assert consensus["requires_manual_check"] is True
    assert consensus["action"] == "MANUAL_CHECK"


def test_track_voter_diplomatic_routes_to_manual_check():
    """Diplomatic plate format must set requires_manual_check=True."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_diplomatic"

    for idx in range(5):
        voter.add_observation(
            track_id=track_id,
            plate_text="77CD1234",
            confidence=0.91,
            bbox=[10, 10, 100, 50],
            frame_ts=10.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["fused_plate"] == "77CD1234"
    assert consensus["format_category"] == "DIPLOMATIC"
    assert consensus["requires_manual_check"] is True
    assert consensus["action"] == "MANUAL_CHECK"


def test_track_voter_temporary_routes_to_manual_check():
    """Temporary registration plates must set requires_manual_check=True."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_temporary"

    for idx in range(5):
        voter.add_observation(
            track_id=track_id,
            plate_text="DL01TEMP1234",
            confidence=0.88,
            bbox=[10, 10, 100, 50],
            frame_ts=10.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["requires_manual_check"] is True
    assert consensus["action"] == "MANUAL_CHECK"


def test_track_voter_unrepairable_noise_routes_to_manual_check():
    """High agreement unrepairable read (non-statutory) must route to MANUAL_CHECK."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_unrepairable"

    for idx in range(5):
        voter.add_observation(
            track_id=track_id,
            plate_text="XX99ZZ9999",
            confidence=0.93,
            bbox=[10, 10, 100, 50],
            frame_ts=10.0 + idx * 0.1,
        )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["format_category"] == "INVALID"
    assert consensus["requires_manual_check"] is True
    assert consensus["action"] == "MANUAL_CHECK"


def test_track_voter_min_consensus_frames_gate():
    """Verifies get_consensus returns None until min_consensus_frames is reached."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_gate"

    for i in range(4):
        voter.add_observation(
            track_id=track_id,
            plate_text="PB65AB1234",
            confidence=0.90,
            bbox=[10, 10, 100, 50],
            frame_ts=float(i),
        )
        assert voter.get_consensus(track_id) is None

    # 5th frame reaches threshold
    voter.add_observation(
        track_id=track_id,
        plate_text="PB65AB1234",
        confidence=0.92,
        bbox=[10, 10, 100, 50],
        frame_ts=4.0,
    )
    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["fused_plate"] == "PB65AB1234"


def test_track_voter_sliding_window_cap():
    """Verifies that buffered observations do not exceed max_track_frames."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_window"

    for i in range(15):
        voter.add_observation(
            track_id=track_id,
            plate_text="PB65AB1234",
            confidence=0.90,
            bbox=[10, 10, 100, 50],
            frame_ts=float(i),
        )

    assert voter.get_track_frame_count(track_id) == 8
    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["frame_count"] == 8


def test_track_voter_clear_track():
    """Verifies clear_track removes all track observations."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_clear"

    for i in range(5):
        voter.add_observation(
            track_id=track_id,
            plate_text="PB65AB1234",
            confidence=0.90,
            bbox=[10, 10, 100, 50],
            frame_ts=float(i),
        )

    assert voter.get_consensus(track_id) is not None
    voter.clear_track(track_id)
    assert voter.get_consensus(track_id) is None
    assert voter.get_track_frame_count(track_id) == 0


def test_track_voter_clearest_frame_selection():
    """Verifies that the highest visual quality frame is returned as best_frame."""
    voter = TrackVoter(min_consensus_frames=5, max_track_frames=8)
    track_id = "trk_sharpness"

    frame_blurry = np.full((100, 200, 3), 120, dtype=np.uint8)
    frame_sharp = np.zeros((100, 200, 3), dtype=np.uint8)
    frame_sharp[::4, ::4] = 255  # high Laplacian variance

    for i in range(4):
        voter.add_observation(
            track_id=track_id,
            plate_text="PB65AB1234",
            confidence=0.88,
            bbox=[10, 10, 50, 20],
            frame_ts=float(i),
            frame_bgr=frame_blurry,
        )

    # 5th frame is sharp
    voter.add_observation(
        track_id=track_id,
        plate_text="PB65AB1234",
        confidence=0.92,
        bbox=[12, 12, 52, 22],
        frame_ts=4.0,
        frame_bgr=frame_sharp,
    )

    consensus = voter.get_consensus(track_id)
    assert consensus is not None
    assert consensus["best_frame"] is frame_sharp
    assert consensus["best_bbox"] == [12, 12, 52, 22]
