"""OCR read assembly and fallback policy; prediction with tracking on a synthetic video (fake detector, real ByteTrack)."""

import numpy as np
import pytest

from anpr_hitl import ocr as ocr_mod
from anpr_hitl.ingest import ingest_video
from anpr_hitl.labels import read_yolo_labels
from anpr_hitl.manifest import read_manifest
from anpr_hitl.ocr import OcrRead, _join_lines, _read, read_plate
from anpr_hitl.predict import frame_flags, predict_images, predict_video, track_consensus, write_predictions
from anpr_hitl.store import read_jsonl
from conftest import fake_reader, make_still, make_video, white_box_detector


# ---------------------------------------------------------------- OCR

def test_two_row_plate_is_read_top_to_bottom_and_hsrp_mark_dropped():
    lines = [  # (y_centre, x_left, height, text, char confs)
        (60, 10, 20, "AB1234", [0.9] * 6),
        (20, 40, 20, "IND", [0.99] * 3),
        (22, 10, 20, "PB65", [0.8, 0.8, 0.7, 0.6]),
    ]
    text, confs = _join_lines(lines)
    assert text == "PB65AB1234"
    assert confs == [0.8, 0.8, 0.7, 0.6] + [0.9] * 6


def test_misaligned_scores_are_dropped_not_guessed():
    read = _read("PB65", [0.9, 0.9], "x", "char", 1)
    assert read.char_confs is None and read.granularity == "none" and read.conf == 0.0


class _Fixed:
    def __init__(self, text, conf):
        self.out = OcrRead(text, conf, [conf] * len(text), "fixed", "char", 1)
        self.calls = 0

    def read(self, crop):
        self.calls += 1
        return OcrRead(**{**self.out.__dict__, "alternatives": []})


@pytest.mark.parametrize("primary, fallback, expected, fallback_called", [
    (("PB65AB1234", 0.95), ("XX", 0.9), "PB65AB1234", False),       # confident primary: fallback not run
    (("", 0.0), ("PB65AB1234", 0.4), "PB65AB1234", True),           # empty primary: fallback read used
    (("PB65AB12", 0.5), ("PB65AB1234", 0.3), "PB65AB1234", True),   # only the fallback matches a format
    (("PB65AB1234", 0.5), ("PB65AB1Z34", 0.9), "PB65AB1234", True), # both run, primary kept, other recorded
])
def test_fallback_policy(monkeypatch, cfg, primary, fallback, expected, fallback_called):
    p, f = _Fixed(*primary), _Fixed(*fallback)
    monkeypatch.setattr(ocr_mod, "get_reader", lambda c, engine=None: f if engine == "tesseract" else p)
    read = read_plate(np.zeros((40, 120, 3), np.uint8), cfg.ocr)
    assert read.text == expected
    assert (f.calls == 1) is fallback_called
    if fallback_called:
        assert len(read.alternatives) == 1  # the other engine's read is kept for the reviewer


def test_track_consensus_majority_then_confidence():
    r = lambda t, c: OcrRead(t, c, [c] * len(t), "f")  # noqa: E731
    assert track_consensus([r("PB65AB1234", .9), r("PB65AB1234", .8), r("PB65A81234", .99)]) == {
        "reads": 3, "consensus": "PB65AB1234", "agreement": 0.667, "disagreement": True}
    tie = track_consensus([r("AA11AA1111", .7), r("BB22BB2222", .9)])
    assert tie["consensus"] == "BB22BB2222" and tie["disagreement"]
    assert track_consensus([r("", 0.0)])["consensus"] == ""


# ---------------------------------------------------------------- predict

def test_video_tracks_carry_one_id_and_every_ingested_frame_is_predicted(tmp_path, cfg, store):
    video = make_video(tmp_path / "cam.mp4", fps=25, seconds=4)
    ingested = ingest_video(video, store, cfg, split="pool").rows
    detector = white_box_detector(0.9)
    round_dir = store.round_dir("t01")
    rows = predict_video(video, ingested, detector, cfg, store, round_dir, fake_reader())
    assert [r["frame_idx"] for r in rows] == [r["frame_idx"] for r in ingested]
    # make_video's plate moves 7 px/frame and wraps back to the left edge at frame 72 (x = 20 + 7i mod 500):
    # one track before the jump, a new one after it
    before = {b["track_id"] for r in rows if r["frame_idx"] < 72 for b in r["boxes"]}
    after = {b["track_id"] for r in rows if r["frame_idx"] >= 72 for b in r["boxes"]}
    assert len(before) == 1 and len(after) == 1 and before != after and None not in before | after
    assert detector.calls["n"] >= 4 * cfg.predict.track_fps      # tracked on the denser stream, not only at 2 fps
    for r in rows:
        assert len(r["boxes"]) == 1
        box = r["boxes"][0]
        assert box["track"]["consensus"] == "PB65AB1234" and not box["track"]["disagreement"]
        assert (round_dir / box["crop"]).is_file()
        labels = read_yolo_labels(round_dir / "predictions" / "labels" / f"{r['frame_id'].replace('/', '__')}.txt")
        assert len(labels) == 1


def test_still_images_flags_and_prelabels(tmp_path, cfg, store):
    items = []
    for i, boxes in enumerate([[(100, 100, 220, 150)], [(50, 60, 170, 110), (400, 200, 520, 250)], []]):
        path = make_still(store.root / "stills" / f"s{i}.jpg", boxes, seed=i)
        items.append({"frame_id": f"public/s{i}", "path": str(path.relative_to(store.root)), "split": "pool",
                      "group": f"g{i}"})
    conf = lambda n, i: 0.45 if n == 1 and i == 1 else 0.9  # noqa: E731 - one uncertain box in image 1
    rows = predict_images(items, white_box_detector(conf), cfg, store, store.round_dir("t02"),
                          fake_reader("PB65AB12", char_conf=[0.9, 0.9, 0.3, 0.9, 0.9, 0.9, 0.9, 0.9]))
    by_id = {r["frame_id"]: r for r in rows}
    assert [len(by_id[f"public/s{i}"]["boxes"]) for i in range(3)] == [1, 2, 0]
    assert "low_confidence" in by_id["public/s1"]["flags"] and "low_confidence" not in by_id["public/s0"]["flags"]
    assert {"regex_failure", "low_char_conf"} <= set(by_id["public/s0"]["flags"])
    assert by_id["public/s2"]["flags"] == ["no_detections"]
    path = write_predictions(store.round_dir("t02"), rows, {"version": "v0001", "weights_sha256": "x"})
    stored = read_jsonl(path)
    assert [r["frame_id"] for r in stored] == sorted(by_id) and all(r["model"]["version"] == "v0001" for r in stored)


def test_frame_flags_band_edges(cfg):
    box = lambda conf: {"conf": conf, "check": {"regex_valid": True, "flags": []}, "ocr": {"text": "X"}}  # noqa: E731
    lo, hi = cfg.select.low_conf_band
    assert "low_confidence" in frame_flags([box(lo)], [], 120, cfg)
    assert "low_confidence" not in frame_flags([box(hi)], [], 120, cfg)
    assert "night" in frame_flags([box(0.9)], [], cfg.select.night_max_luma - 1, cfg)
    assert "near_miss" in frame_flags([box(0.9)], [{"conf": 0.15}], 120, cfg)


def test_ingested_manifest_paths_resolve(tmp_path, cfg, store):
    video = make_video(tmp_path / "v.mp4", fps=25, seconds=2)
    ingest_video(video, store, cfg, split="pool")
    assert all((store.root / r["path"]).is_file() for r in read_manifest(store.frames_manifest))
