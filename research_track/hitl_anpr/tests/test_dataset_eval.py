"""Dataset assembly (replay, GOLD exclusion), GOLD evaluation maths and integrity, and the stopping rule."""

import shutil
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from anpr_hitl.dataset import LeakageError, assemble, replay_count
from anpr_hitl.evaluate import (DetEval, GoldIntegrityError, bootstrap_det, det_metrics, levenshtein,
                                match_predictions, ocr_metrics, verify_gold)
from anpr_hitl.hashing import image_dhash, sha256_file
from anpr_hitl.labels import read_yolo_labels, write_yolo_labels, xyxy_to_yolo
from anpr_hitl.manifest import write_manifest
from anpr_hitl.rounds import should_stop
from anpr_hitl.store import atomic_write_json
from conftest import make_still


# ---------------------------------------------------------------- replay

@pytest.mark.parametrize("n_new", [1, 7, 50, 300, 1000])
@pytest.mark.parametrize("fraction", [0.3, 0.5])
def test_replay_share_is_at_least_the_configured_fraction(n_new, fraction):
    k = replay_count(n_new, 10_000, fraction)
    assert k / (n_new + k) >= fraction and (k - 1) / (n_new + k - 1) < fraction


def test_replay_is_capped_by_old_data():
    assert replay_count(300, 40, 0.3) == 40
    assert replay_count(300, 0, 0.3) == 0
    assert replay_count(0, 40, 0.3) == 40


# ---------------------------------------------------------------- assembly

def _bootstrap(store, n_seed=6, n_val=3, n_gold=3):
    det = store.bootstrap_dir / "detector"
    rows = []
    for split, n, offset in (("seed", n_seed, 100), ("val", n_val, 200)):
        for i in range(n):
            box = (30 + 15 * i, 60, 150 + 15 * i, 110)
            img = make_still(det / split / "images" / f"{split}{i}.jpg", [box], seed=offset + i)
            write_yolo_labels(det / split / "labels" / f"{split}{i}.txt", [(0, *xyxy_to_yolo(box, 640, 360))])
            rows.append({"image_id": f"{split}{i}", "split": split, "path": str(img.relative_to(store.root)),
                         "dhash": f"{image_dhash(img):016x}", "group": f"{split}{i}", "source": "synthetic"})
    write_manifest(det / "manifest.jsonl", rows)
    gold = store.gold_dir / "det"
    gold_rows = []
    for i in range(n_gold):
        box = (200, 150 + 10 * i, 330, 200 + 10 * i)
        img = make_still(gold / "images" / f"gold{i}.jpg", [box], seed=300 + i)
        label = gold / "labels" / f"gold{i}.txt"
        write_yolo_labels(label, [(0, *xyxy_to_yolo(box, 640, 360))])
        gold_rows.append({"image_id": f"gold{i}", "path": str(img.relative_to(store.root)), "sha256": sha256_file(img),
                          "label_sha256": sha256_file(label), "dhash": f"{image_dhash(img):016x}",
                          "source": "synthetic", "split": "gold", "boxes": 1})
    gold_hash = write_manifest(gold / "manifest.jsonl", gold_rows)
    atomic_write_json(gold / "gold.json", {"kind": "detector", "frozen": True, "manifest_sha256": gold_hash})
    ocr = store.gold_dir / "ocr"
    crop_rows = []
    for i in range(2):
        crop = make_still(ocr / "crops" / f"c{i}.jpg", [(2, 2, 100, 30)], size=(110, 34), seed=400 + i)
        crop_rows.append({"crop_id": f"c{i}", "path": str(crop.relative_to(store.root)), "text": "PB65AB1234",
                          "source": "synthetic", "format_valid": True, "sha256": sha256_file(crop)})
    atomic_write_json(ocr / "gold.json", {"kind": "ocr", "manifest_sha256": write_manifest(ocr / "manifest.jsonl", crop_rows)})
    return gold_rows


class _Decisions:
    """Stand-in for ReviewService.trainable(): approved frames with human boxes."""

    def __init__(self, store, n, round_id="r01", seed=500):
        self.rows = []
        for i in range(n):
            box = (60 + 10 * i, 200, 180 + 10 * i, 250)
            img = make_still(store.root / "frames" / "vid" / f"{i:06d}.jpg", [box], seed=seed + i)
            self.rows.append({"round": round_id, "frame_id": f"vid/{i:06d}", "path": str(img.relative_to(store.root)),
                              "boxes": [{"xyxy": list(box)}], "source": "human", "hash": f"h{i}"})

    def trainable(self, rounds):
        return [r for r in self.rows if r["round"] in rounds]


def test_assemble_uses_reviewed_boxes_plus_replay(cfg, store):
    _bootstrap(store)
    summary = assemble(store, cfg, "r01", _Decisions(store, 7))
    assert summary["new_reviewed"] == 7 and summary["replay"] == 3 and summary["replay_share"] >= 0.3
    out = store.dataset_dir("r01")
    labels = sorted((out / "train" / "labels").glob("*.txt"))
    assert len(labels) == 10 and len(list((out / "val" / "images").iterdir())) == 3
    first = next(p for p in labels if "vid__000000" in p.name)
    (cx, cy, w, h), = [lab[1:] for lab in read_yolo_labels(first)]
    assert (cx * 640, w * 640) == pytest.approx((120, 120), abs=0.01)   # the reviewer's box, in YOLO form
    with pytest.raises(FileExistsError):
        assemble(store, cfg, "r01", _Decisions(store, 7))
    assert assemble(store, cfg, "r01", _Decisions(store, 4), force=True)["train_images"] == 6


def test_gold_images_can_never_enter_training(cfg, store):
    gold_rows = _bootstrap(store)
    decisions = _Decisions(store, 3)
    shutil.copyfile(store.root / gold_rows[0]["path"], store.root / decisions.rows[1]["path"])  # GOLD copy
    with pytest.raises(LeakageError, match="byte-identical"):
        assemble(store, cfg, "r01", decisions)
    from PIL import Image

    img = Image.open(store.root / gold_rows[0]["path"])
    img.save(store.root / decisions.rows[1]["path"], quality=70)         # re-encoded GOLD frame
    with pytest.raises(LeakageError, match="near-duplicates"):
        assemble(store, cfg, "r01", decisions)


# ---------------------------------------------------------------- evaluation maths

def _ultralytics_match(gt, pred):
    from ultralytics.engine.validator import BaseValidator
    from ultralytics.utils.metrics import box_iou

    holder = SimpleNamespace(iouv=torch.linspace(0.5, 0.95, 10))
    iou = box_iou(torch.tensor(gt, dtype=torch.float32), torch.tensor(pred, dtype=torch.float32))
    return BaseValidator.match_predictions(holder, torch.zeros(len(pred)), torch.zeros(len(gt)), iou).numpy()


def test_matching_reproduces_ultralytics_validator():
    rng = np.random.default_rng(0)
    for _ in range(50):
        gt = rng.uniform(0, 500, (int(rng.integers(1, 6)), 2))
        gt = np.concatenate([gt, gt + rng.uniform(20, 120, gt.shape)], axis=1)
        pred = np.concatenate([gt + rng.normal(0, 8, gt.shape), rng.uniform(0, 600, (2, 4))])
        pred[:, 2:] = np.maximum(pred[:, 2:], pred[:, :2] + 1)
        assert np.array_equal(match_predictions(gt, pred), _ultralytics_match(gt, pred))


def test_det_metrics_perfect_and_empty():
    gt = np.array([[10, 10, 50, 30], [100, 100, 160, 130]], dtype=float)
    tp = match_predictions(gt, gt)
    m = det_metrics(tp, np.array([0.9, 0.8]), 2, 0.25)
    assert m["map50"] == pytest.approx(0.995, abs=0.001) and m["precision"] == 1 and m["recall"] == 1
    assert det_metrics(np.zeros((0, 10), bool), np.zeros(0), 2, 0.25)["recall"] == 0.0


def test_bootstrap_ci_brackets_estimate_and_paired_self_difference_is_zero():
    rng = np.random.default_rng(1)
    ids, tps, confs, n_gt = [], [], [], []
    for i in range(60):
        n = int(rng.integers(1, 4))
        tp = np.tile(rng.random(n)[:, None] < 0.8, (1, 10))
        ids.append(f"i{i}")
        tps.append(tp)
        confs.append(rng.random(n))
        n_gt.append(n)
    ev = DetEval(ids, tps, confs, n_gt, [{}] * 60)
    ci = bootstrap_det(ev, 200, 0, 0.25)
    point = ev.metrics(op_conf=0.25)["map50"]
    assert ci["map50"][0] <= point <= ci["map50"][1]
    assert bootstrap_det(ev, 50, 0, 0.25, other=ev) == {"map50": [0.0, 0.0], "map50_95": [0.0, 0.0]}


def test_det_eval_round_trips_through_npz(tmp_path):
    ev = DetEval(["a", "b"], [np.ones((2, 10), bool), np.zeros((0, 10), bool)], [np.array([0.9, 0.2]), np.zeros(0)],
                 [2, 0], [{"source": "x"}, {"source": "y"}])
    ev.save(tmp_path / "e.npz")
    back = DetEval.load(tmp_path / "e.npz")
    assert back.image_ids == ev.image_ids and back.n_gt == ev.n_gt and back.attrs == ev.attrs
    assert all(np.array_equal(a, b) for a, b in zip(back.tp, ev.tp))


def test_levenshtein_and_ocr_metrics():
    assert levenshtein("PB65AB1234", "PB65AB1234") == 0
    assert levenshtein("PB65AB1234", "P865AB1234") == 1
    assert levenshtein("PB65AB1234", "PB65A1234") == 1
    assert levenshtein("", "AB") == 2
    m = ocr_metrics([{"text": "AB12", "pred": "AB12"}, {"text": "AB12", "pred": "A812"}])
    assert m["exact"] == 0.5 and m["cer"] == pytest.approx(1 / 8)


@pytest.mark.parametrize("tamper", ["label", "image", "extra_file", "manifest"])
def test_gold_integrity_detects_any_change(cfg, store, tamper):
    gold_rows = _bootstrap(store)
    info = verify_gold(store)
    assert info["det_images"] == 3 and len(info["gold_manifest_sha256"]) == 64
    det = store.gold_dir / "det"
    if tamper == "label":
        write_yolo_labels(det / "labels" / "gold1.txt", [])                       # a plate "removed" from GOLD
    elif tamper == "image":
        (store.root / gold_rows[2]["path"]).write_bytes(b"not the frozen image")
    elif tamper == "extra_file":
        shutil.copyfile(store.root / gold_rows[0]["path"], det / "images" / "sneaked_in.jpg")
    else:
        write_manifest(det / "manifest.jsonl", gold_rows[:2])                      # a row dropped from GOLD
    with pytest.raises(GoldIntegrityError):
        verify_gold(store)


# ---------------------------------------------------------------- stopping rule

def test_stopping_rule(cfg):
    h = lambda r, g, e=None: {"round": r, "gain_map50_95_pt": g, "gain_exact_pt": e}  # noqa: E731
    assert should_stop([], cfg, 0) == (False, "continue")
    assert should_stop([h("r1", 0.2), h("r2", 0.4)], cfg, 10)[0]
    assert not should_stop([h("r1", 0.2), h("r2", 0.6)], cfg, 10)[0]
    assert not should_stop([h("r1", 0.2), h("r2", 0.1, e=3.0)], cfg, 10)[0]   # an OCR gain counts too
    assert not should_stop([h("r1", 0.1)], cfg, 10)[0]                        # needs two rounds
    assert should_stop([], cfg, cfg.run_round.total_review_budget)[0]


def test_champion_is_re_evaluated_when_the_comparison_would_be_unfair(cfg, store, tmp_path, monkeypatch):
    import anpr_hitl.rounds as rounds
    from anpr_hitl.evaluate import ocr_config_hash
    from anpr_hitl.registry import Registry

    calls = []

    def fake_eval(store_, cfg_, weights, name):
        calls.append(name)
        (rounds.eval_dir(store_, name)).mkdir(parents=True, exist_ok=True)
        return {"gold_manifest_sha256": "g", "eval_version": rounds.EVAL_VERSION,
                "ocr": {"ocr_config_sha256": ocr_config_hash(cfg_)}}

    monkeypatch.setattr(rounds, "evaluate_weights", fake_eval)
    weights = tmp_path / "w.pt"
    weights.write_bytes(b"w")
    reg = Registry(store)
    current = {"gold_manifest_sha256": "g", "eval_version": rounds.EVAL_VERSION, "eval_name": "boot",
               "ocr": {"ocr_config_sha256": ocr_config_hash(cfg)}}
    v = reg.register(weights, cfg, "d", "r00", current)["version"]
    reg.promote(v, {}, "t")
    (rounds.eval_dir(store, "boot")).mkdir(parents=True)
    (rounds.eval_dir(store, "boot") / "det_eval.npz").write_bytes(b"x")
    assert rounds.champion_metrics(store, cfg, reg, "g")[0]["eval_name"] == "boot" and calls == []
    assert rounds.champion_metrics(store, cfg, reg, "other-gold")[1].name == f"{v}_reeval"
    stale = {**current, "ocr": {"ocr_config_sha256": "older-ocr-settings"}}
    v2 = reg.register(weights, cfg, "d", "r01", stale)["version"]
    reg.promote(v2, {}, "t")
    rounds.champion_metrics(store, cfg, reg, "g")
    assert calls == [f"{v}_reeval", f"{v2}_reeval"]
