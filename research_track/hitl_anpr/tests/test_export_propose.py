"""Frigate decoding, export parity matching, backend proposals (dry run), model card, registry CLI."""

import numpy as np
import pytest

from anpr_hitl.cli import main
from anpr_hitl.config import load_config
from anpr_hitl.export import FRIGATE_MAX, frigate_decode, match_sets
from anpr_hitl.modelcard import write_model_card
from anpr_hitl.propose import build_proposals, mask_plate, propose
from anpr_hitl.registry import Registry
from anpr_hitl.store import write_jsonl


def _raw(boxes_scores, anchors=50):
    """A (1, 5, anchors) one-class raw head output: cx, cy, w, h, score per anchor."""
    out = np.zeros((1, 5, anchors), np.float32)
    for k, ((x1, y1, x2, y2), s) in enumerate(boxes_scores):
        out[0, :, k] = [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, s]
    return out


def test_frigate_decoder_threshold_nms_and_layout():
    raw = _raw([((100, 200, 220, 240), 0.9), ((102, 201, 221, 241), 0.85),   # duplicate -> NMS
                ((400, 100, 500, 130), 0.5), ((10, 10, 60, 30), 0.39)])         # below Frigate's 0.4 floor
    dec = frigate_decode(raw, 640, 640)
    kept = dec[dec[:, 1] > 0]
    assert len(kept) == 2 and dec.shape == (FRIGATE_MAX, 6)
    cls, score, y1, x1, y2, x2 = kept[0]
    assert (cls, score) == (0, pytest.approx(0.9))
    assert (y1, x1, y2, x2) == pytest.approx((200 / 640, 100 / 640, 240 / 640, 220 / 640))   # y-first, 0..1
    many = _raw([((20 * i, 0, 20 * i + 15, 10), 0.9) for i in range(30)])
    assert (frigate_decode(many, 640, 640)[:, 1] > 0).sum() == FRIGATE_MAX


def test_parity_matching_counts_box_and_confidence_agreement():
    a = np.array([[0, 0, 100, 50], [200, 200, 300, 250]], float)
    b = np.array([[1, 0, 101, 50], [200, 200, 300, 250], [500, 500, 600, 550]], float)
    m = match_sets(a, [0.9, 0.5], b, [0.905, 0.6, 0.7], min_iou=0.9, max_drift=0.02)
    assert (m["a"], m["b"], m["matched"], m["matched_within_drift"]) == (2, 3, 2, 1)


def _video_rows():
    def box(track, text, conf, ocr_conf, consensus):
        return {"track_id": track, "conf": conf, "xyxy": [0, 0, 10, 5],
                "ocr": {"text": text, "conf": ocr_conf, "engine": "rapidocr"},
                "check": {"regex_valid": True, "format": "standard", "flags": []},
                "track": {"consensus": consensus, "reads": 3, "agreement": 0.67}}
    model = {"version": "v0002", "weights_sha256": "f" * 64}
    return [
        {"kind": "video", "video_id": "cam-1", "frame_id": "cam-1/000000", "model": model,
         "boxes": [box(1, "PB65AB1234", 0.8, 0.91, "PB65AB1234"), box(2, "", 0.5, 0.0, "")]},
        {"kind": "video", "video_id": "cam-1", "frame_id": "cam-1/000012", "model": model,
         "boxes": [box(1, "PB65A81234", 0.9, 0.95, "PB65AB1234")]},
        {"kind": "image", "frame_id": "public/x", "model": model, "boxes": [box(None, "DL01AB0001", 0.9, 0.9, "")]},
    ]


def test_one_proposal_per_track_with_consensus_read():
    payloads = build_proposals(_video_rows(), "GATE-1")
    assert len(payloads) == 1                                   # empty-read track and still images are skipped
    p = payloads[0]
    assert p["source"] == "OTHER" and p["gate_id"] == "GATE-1" and p["metadata_payload"]["proposal"] is True
    assert p["raw_plate"] == "PB65AB1234" and p["plate_confidence"] == 0.91   # the consensus read's own confidence
    assert p["source_event_id"] == "hitl:cam-1:1:v0002" and len(p["source_event_id"]) <= 100
    assert p["metadata_payload"]["detector_conf"] == 0.9


def test_propose_is_a_dry_run_by_default_and_masks_console_text(cfg, store):
    write_jsonl(store.predictions_dir("r09") / "predictions.jsonl", _video_rows())
    report = propose(store, cfg, "r09", "GATE-1")
    assert report["dry_run"] and report["proposals"] == 1 and "http_status_counts" not in report
    assert report["examples"][0]["plate"] == "PB******34"
    assert mask_plate("AB12") == "AB**"


def test_model_card_and_registry_cli(cfg, store, tmp_path, capsys):
    weights = tmp_path / "w.pt"
    weights.write_bytes(b"weights")
    metrics = {"gold_manifest_sha256": "g" * 64, "op_conf": 0.25, "imgsz": 1280,
               "detection": {"precision": 0.9, "recall": 0.8, "map50": 0.85, "map50_95": 0.5, "n": 538, "images": 386,
                             "ci95": {"map50": [0.82, 0.88], "map50_95": [0.47, 0.53]}},
               "ocr": {"exact": 0.7, "cer": 0.1, "n": 2591, "engine": "rapidocr", "ocr_config_sha256": "c" * 16,
                       "ci95": {"exact": [0.68, 0.72]}},
               "slices": {"det:night": {"n": 40, "value": 0.7}}}
    reg = Registry(store)
    v = reg.register(weights, cfg, "d" * 64, "r00", metrics, gold_sha256="g" * 64)["version"]
    reg.promote(v, {"promote": True, "reasons": ["first model"], "gains_pt": {}}, "test")
    card = write_model_card(store, cfg, v).read_text()
    for needle in (v, "d" * 64, cfg.sha256(), "50.00", "47.00–53.00", "AGPL-3.0", "must not open", "DPDP"):
        assert needle in card, needle
    assert "$" not in card.split("## Reproduce")[0]                 # every placeholder filled
    assert main(["--data-root", str(cfg.data_root), "registry"]) == 0
    out = capsys.readouterr().out
    assert "CHAMPION" in out and v in out
    assert main(["--data-root", str(cfg.data_root), "registry", "verify"]) == 0


def test_config_rejects_mirroring_and_multiclass():
    with pytest.raises(ValueError):
        load_config(train={"fliplr": 0.5})
    with pytest.raises(ValueError):
        load_config(class_names=["license_plate", "car"])
