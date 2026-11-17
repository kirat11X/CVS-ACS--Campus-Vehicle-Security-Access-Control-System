"""Selection (audit sample, budget, diversity), the review service's training gate, and the simulated oracle."""

import json

import pytest

from anpr_hitl.chainlog import ChainError
from anpr_hitl.hashing import image_dhash, sha256_file
from anpr_hitl.labels import write_yolo_labels, xyxy_to_yolo
from anpr_hitl.oracle import ORACLE_REVIEWER, oracle_review
from anpr_hitl.predict import predict_images, write_predictions
from anpr_hitl.review.service import ReviewedBox, ReviewError, ReviewService, wilson_lower
from anpr_hitl.selection import select_frames, write_queue
from conftest import fake_reader, make_still, white_box_detector

N_FRAMES = 12


def _row(i, flags=(), conf=0.9, split="pool", group=None, dhash=None):
    return {"frame_id": f"f{i:03d}", "path": f"x/{i}.jpg", "split": split, "group": group or f"g{i}",
            "kind": "image", "flags": list(flags), "dhash": dhash or f"{(i * 0x9E3779B97F4A7C15) % 2**64:016x}",
            "boxes": [{"conf": conf, "ocr": {"text": "PB65AB1234"}, "check": {"format": "standard"}}],
            "near_misses": []}


# ---------------------------------------------------------------- selection

def test_selection_budget_audit_and_determinism(cfg):
    rows = [_row(i, flags=["low_confidence"] if i % 3 == 0 else []) for i in range(200)]
    rows += [_row(900 + i, split=s) for i, s in enumerate(["val", "gold", "gold"])]
    sel = select_frames(rows, cfg, "r01", decided=set(), reviewed_total=0, budget=50)
    items = sel["items"]
    assert len(items) == 50 and sel["summary"]["audit"] == 5             # 10% random audit inside the budget
    assert all(it["split"] == "pool" for it in items)                     # val / GOLD never selected
    ranked = [it for it in items if not it["audit"]]
    assert all("low_confidence" in it["reasons"] for it in ranked)        # uncertainty fills the rest
    again = select_frames(rows, cfg, "r01", decided=set(), reviewed_total=0, budget=50)["items"]
    assert again == items                                                 # deterministic per round
    other = select_frames(rows, cfg, "r02", decided=set(), reviewed_total=0, budget=50)["items"]
    assert {i["frame_id"] for i in other if i["audit"]} != {i["frame_id"] for i in items if i["audit"]}


def test_selection_respects_decisions_total_budget_group_cap_and_near_duplicates(cfg):
    rows = [_row(i, flags=["regex_failure"]) for i in range(40)]
    decided = {f"f{i:03d}" for i in range(10)}
    sel = select_frames(rows, cfg, "r01", decided, reviewed_total=cfg.run_round.total_review_budget - 7, budget=50)
    assert len(sel["items"]) == 7 and not decided & {i["frame_id"] for i in sel["items"]}
    one_site = [_row(i, flags=["regex_failure"], group="gate-1") for i in range(40)]
    capped = select_frames(one_site, cfg.model_copy(update={"select": cfg.select.model_copy(
        update={"audit_fraction": 0.0})}), "r01", set(), 0, budget=20)
    assert len(capped["items"]) == 5 and capped["summary"]["skipped_group_cap"] > 0   # 25% of 20
    dups = [_row(i, flags=["regex_failure"], dhash="00000000000000ff") for i in range(10)]
    deduped = select_frames(dups, cfg.model_copy(update={"select": cfg.select.model_copy(
        update={"audit_fraction": 0.0})}), "r01", set(), 0, budget=10)
    assert len(deduped["items"]) == 1 and deduped["summary"]["skipped_near_duplicate"] == 9


def test_wilson_bound_needs_about_190_perfect_audits_for_98_percent():
    assert wilson_lower(150, 150) < 0.98                 # the configured minimum of 150 items is not enough alone
    assert wilson_lower(188, 188) < 0.98 <= wilson_lower(189, 189)
    assert wilson_lower(0, 0) == 0.0
    assert 0.80 < wilson_lower(90, 100) < 0.90


# ---------------------------------------------------------------- review service

@pytest.fixture
def public_round(cfg, store):
    """12 public-pool stills with white 'plates', fake predictions, a queue, and oracle labels offset by 3 px."""
    items = []
    for i in range(N_FRAMES):
        boxes = [(40 + 20 * i, 80, 160 + 20 * i, 130)] + ([(400, 220, 520, 270)] if i % 2 else [])
        path = make_still(store.bootstrap_dir / "detector" / "pool" / "images" / f"img{i}.jpg", boxes, seed=i)
        oracle_boxes = [(x1 + 3, y1 + 3, x2 + 3, y2 + 3) for x1, y1, x2, y2 in boxes]
        if i == 5:
            oracle_boxes.append((300, 20, 360, 45))         # a plate the model will miss
        write_yolo_labels(store.bootstrap_dir / "detector" / "pool" / "oracle_labels" / f"img{i}.txt",
                          [(0, *xyxy_to_yolo(b, 640, 360)) for b in oracle_boxes])
        items.append({"frame_id": f"public/img{i}", "path": str(path.relative_to(store.root)), "split": "pool",
                      "group": f"g{i}", "dhash": f"{image_dhash(path):016x}", "oracle_label": True,
                      "sha256": sha256_file(path)})
    round_dir = store.round_dir("r01")
    rows = predict_images(items, white_box_detector(0.9), cfg, store, round_dir, fake_reader())
    write_predictions(round_dir, rows, {"version": "v0001", "weights_sha256": "abc"})
    write_queue(round_dir, select_frames(rows, cfg, "r01", set(), 0, budget=N_FRAMES))
    return ReviewService(store, cfg)


def _proposal(svc, item):
    pred = svc.predictions("r01")[item["frame_id"]]
    return [ReviewedBox(tuple(b["xyxy"]), b["ocr"]["text"]) for b in pred["boxes"]]


def test_only_complete_accepted_or_corrected_frames_are_trainable(public_round):
    svc = public_round
    q = svc.queue("r01")
    assert len(q) == N_FRAMES
    svc.submit("r01", q[0]["item_id"], "accept", _proposal(svc, q[0]), True, "asha")
    fixed = _proposal(svc, q[1])
    fixed[0].text = "PB65AB1235"
    svc.submit("r01", q[1]["item_id"], "correct", fixed, True, "asha")
    svc.submit("r01", q[2]["item_id"], "correct", _proposal(svc, q[2])[:1], False, "asha")  # not all boxed
    svc.submit("r01", q[3]["item_id"], "reject", [], False, "asha")
    svc.submit("r01", q[4]["item_id"], "skip", [], False, "asha")
    trainable = {e["item_id"] for e in svc.trainable({"r01"})}
    assert trainable == {q[0]["item_id"], q[1]["item_id"]}
    assert svc.pending("r01")[-1]["item_id"] == q[4]["item_id"]          # skipped items come last
    svc.submit("r01", q[0]["item_id"], "reject", [], False, "lead")     # a later decision supersedes
    assert {e["item_id"] for e in svc.trainable({"r01"})} == {q[1]["item_id"]}
    assert svc.log.verify() == []
    s = svc.summary("r01")
    assert (s["accept"], s["correct"], s["reject"], s["skip"], s["incomplete_frames"]) == (0, 2, 2, 1, 1)


def test_submit_validates_input(public_round):
    svc = public_round
    item = svc.queue("r01")[0]
    proposal = _proposal(svc, item)
    with pytest.raises(ReviewError, match="reviewer"):
        svc.submit("r01", item["item_id"], "accept", proposal, True, "  ")
    with pytest.raises(ReviewError, match="outside"):
        svc.submit("r01", item["item_id"], "correct", [ReviewedBox((0, 0, 9999, 10), "PB65AB1234")], True, "a")
    with pytest.raises(ReviewError, match="text"):
        svc.submit("r01", item["item_id"], "correct", [ReviewedBox(proposal[0].xyxy, "")], True, "a")
    changed = [ReviewedBox(proposal[0].xyxy, "DL01AB0001")] + proposal[1:]
    with pytest.raises(ReviewError, match="accept"):
        svc.submit("r01", item["item_id"], "accept", changed, True, "a")
    with pytest.raises(ReviewError, match="not in"):
        svc.submit("r01", "r01:public/nope", "accept", proposal, True, "a")
    svc.submit("r01", item["item_id"], "correct", [ReviewedBox(proposal[0].xyxy, "", "unreadable")], True, "a")


def test_changed_frame_is_refused_and_never_trained_on(public_round, store):
    svc = public_round
    item = svc.queue("r01")[0]
    svc.submit("r01", item["item_id"], "accept", _proposal(svc, item), True, "asha")
    frame = store.root / item["path"]
    frame.write_bytes(frame.read_bytes() + b"\0")
    assert svc.trainable({"r01"}) == []
    with pytest.raises(ReviewError, match="changed on disk"):
        svc.submit("r01", item["item_id"], "accept", _proposal(svc, item), True, "asha")


def test_tampered_audit_log_is_detected(public_round, store):
    svc = public_round
    item = svc.queue("r01")[0]
    svc.submit("r01", item["item_id"], "reject", [], False, "asha")
    lines = store.audit_log.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["decision"] = "accept"
    store.audit_log.write_text(json.dumps(entry) + "\n")
    assert svc.log.verify()
    with pytest.raises(ChainError):
        svc.trainable()


def test_auto_accept_gate(public_round, monkeypatch):
    svc = public_round
    assert svc.auto_accept_allowed() == (False, "auto-accept is disabled in config.yaml")
    svc.cfg = svc.cfg.model_copy(update={"review": svc.cfg.review.model_copy(update={
        "auto_accept": svc.cfg.review.auto_accept.model_copy(update={"enabled": True})})})
    monkeypatch.setattr(svc, "audit_stats", lambda: {"n": 150, "wilson_lower": wilson_lower(150, 150)})
    assert svc.auto_accept_allowed()[0] is False
    monkeypatch.setattr(svc, "audit_stats", lambda: {"n": 200, "wilson_lower": wilson_lower(200, 200)})
    assert svc.auto_accept_allowed()[0] is True


def test_oracle_uses_human_labels_and_measures_the_model(public_round, store):
    svc = public_round
    counts = oracle_review(svc, "r01")
    assert counts["reviewed"] == N_FRAMES
    decisions = list(svc.decisions().values())
    assert all(e["source"] == "oracle" and e["reviewer"] == ORACLE_REVIEWER for e in decisions)
    by_frame = {e["frame_id"]: e for e in decisions}
    missed = by_frame["public/img5"]
    assert len(missed["boxes"]) == len(missed["proposal"]) + 1 and not missed["model_correct"]
    ok = by_frame["public/img0"]
    assert ok["model_correct"] and ok["boxes"][0]["xyxy"] != ok["proposal"][0]["xyxy"]   # human box, not the model's
    assert all(b["text_status"] == "not_reviewed" for e in decisions for b in e["boxes"])
    assert counts["model_correct"] == N_FRAMES - 1
    assert len(svc.trainable({"r01"})) == N_FRAMES
    assert svc.audit_stats()["n"] == sum(e["audit"] for e in decisions)


def test_review_app_records_a_human_decision(public_round, store, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from anpr_hitl.review import app as app_module

    monkeypatch.setenv("ANPR_REVIEW_ROUND", "r01")
    monkeypatch.setenv("ANPR_DATA_ROOT", str(store.root))
    monkeypatch.setenv("ANPR_REVIEWER", "asha")
    at = AppTest.from_file(app_module.__file__, default_timeout=60).run()
    assert not at.exception
    first = public_round.pending("r01")[0]
    assert first["frame_id"] in at.subheader[0].value
    accept = next(b for b in at.button if b.label == "Accept as proposed")
    assert not accept.disabled                                  # nothing edited yet
    next(c for c in at.checkbox if c.label.startswith("Every plate")).check()
    at = accept.click().run()
    assert not at.exception
    decision = public_round.decisions()[first["item_id"]]
    assert (decision["decision"], decision["source"], decision["reviewer"], decision["all_plates_boxed"]) == (
        "accept", "human", "asha", True)
    assert first["frame_id"] not in at.subheader[0].value       # moved on to the next frame
    text_box = at.text_input[0]
    at = text_box.set_value("PB65AB9999").run()                 # an edit disables "accept"
    assert next(b for b in at.button if b.label == "Accept as proposed").disabled
