"""One round of the loop, resumable stage by stage:

  predict -> select -> review -> assemble -> train -> evaluate + gate -> register (promote or reject)

Each finished stage is recorded in rounds/<id>/state.json; re-running a round continues from the first unfinished
stage. The review stage waits for people (the simulated oracle can answer public-pool frames). The loop stops when
the GOLD gain stays below stop_gain_pt for stop_patience_rounds consecutive rounds, or the review budget is spent.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from anpr_hitl.config import Config
from anpr_hitl.evaluate import DetEval, bootstrap_det, evaluate_model, ocr_config_hash
from anpr_hitl.ingest import find_videos, video_id_for
from anpr_hitl.hashing import sha256_file
from anpr_hitl.manifest import read_manifest
from anpr_hitl.predict import YoloDetector, model_info, predict_images, predict_video, write_predictions
from anpr_hitl.promote import promotion_gate
from anpr_hitl.registry import Registry
from anpr_hitl.review.service import ReviewService
from anpr_hitl.selection import select_frames, write_queue
from anpr_hitl.splits import VideoRegistry
from anpr_hitl.store import Store, atomic_write_json, read_json

EVAL_VERSION = 1  # bump when evaluation code changes; older stored metrics are then recomputed, not compared


def state_path(store: Store, round_id: str) -> Path:
    return store.round_dir(round_id) / "state.json"


def round_state(store: Store, round_id: str) -> dict:
    return read_json(state_path(store, round_id), {"round": round_id, "stages": {}})


def mark(store: Store, round_id: str, stage: str, info: dict) -> None:
    state = round_state(store, round_id)
    state["stages"][stage] = {**info, "ts": time.time()}
    atomic_write_json(state_path(store, round_id), state)


# ---------------------------------------------------------------- predict

def public_pool_items(store: Store) -> list[dict]:
    rows = read_manifest(store.bootstrap_dir / "detector" / "manifest.jsonl")
    return [{"frame_id": f"public/{r['image_id']}", "path": r["path"], "split": "pool", "group": r["group"],
             "source": r["source"], "dhash": r["dhash"], "oracle_label": True, "sha256": sha256_file(store.root / r["path"])}
            for r in rows if r["split"] == "pool"]


def pool_videos(store: Store, cfg: Config, video_paths: list[Path]) -> list[tuple[Path, list[dict]]]:
    """(video file, its ingested pool frames) for registered pool videos found among video_paths."""
    registry = VideoRegistry(store.videos_registry, cfg.seed, cfg.splits.gold_fraction, cfg.splits.val_fraction)
    videos = registry.all()
    frames = read_manifest(store.frames_manifest)
    out = []
    for path in find_videos(video_paths):
        vid = video_id_for(path, sha256_file(path))
        if vid in videos and videos[vid]["split"] == "pool":
            out.append((path, [f for f in frames if f["video_id"] == vid]))
    return out


def prediction_summary(rows: list[dict]) -> dict:
    boxes = [b for r in rows for b in r["boxes"]]
    flags = Counter(f for r in rows for f in r["flags"])
    return {"frames": len(rows), "boxes": len(boxes),
            "frames_with_boxes": sum(1 for r in rows if r["boxes"]),
            "regex_valid_reads": sum(b["check"]["regex_valid"] for b in boxes),
            "empty_reads": sum(not b["ocr"]["text"] for b in boxes),
            "mean_det_conf": round(sum(b["conf"] for b in boxes) / len(boxes), 4) if boxes else None,
            "tracks": len({(r.get("video_id"), b.get("track_id")) for r in rows for b in r["boxes"]
                           if b.get("track_id") is not None}),
            "flags": dict(sorted(flags.items()))}


def predict_round(store: Store, cfg: Config, round_id: str, weights: Path, version: str | None,
                  sources: set[str], video_paths: list[Path] | None = None, detector=None, reader=None) -> dict:
    round_dir = store.round_dir(round_id)
    detector = detector or YoloDetector(weights, cfg.predict.imgsz, min(cfg.predict.conf, 0.1), cfg.predict.iou,
                                        cfg.predict.device)
    rows = []
    started = time.time()
    if "public" in sources:
        rows += predict_images(public_pool_items(store), detector, cfg, store, round_dir, reader)
    if "video" in sources:
        for path, frames in pool_videos(store, cfg, video_paths or []):
            rows += predict_video(path, frames, detector, cfg, store, round_dir, reader)
    model = model_info(weights, version)
    write_predictions(round_dir, rows, model)
    summary = {**prediction_summary(rows), "model": model, "sources": sorted(sources),
               "seconds": round(time.time() - started, 1)}
    mark(store, round_id, "predict", summary)
    return summary


# ---------------------------------------------------------------- select / review

def reviewed_total(service: ReviewService) -> int:
    return sum(1 for e in service.decisions().values() if e["decision"] != "skip" and e["source"] != "auto")


def select_round(store: Store, cfg: Config, round_id: str, service: ReviewService, budget: int | None = None) -> dict:
    from anpr_hitl.store import read_jsonl

    rows = read_jsonl(store.predictions_dir(round_id) / "predictions.jsonl")
    selection = select_frames(rows, cfg, round_id, service.decided_frames(), reviewed_total(service), budget)
    queue_hash = write_queue(store.round_dir(round_id), selection)
    summary = {**selection["summary"], "queue_sha256": queue_hash}
    mark(store, round_id, "select", summary)
    return summary


# ---------------------------------------------------------------- evaluate / gate / register

def eval_dir(store: Store, name: str) -> Path:
    return store.root / "evals" / name


def evaluate_weights(store: Store, cfg: Config, weights: Path, name: str) -> dict:
    metrics = evaluate_model(weights, store, cfg, eval_dir(store, name))
    metrics["eval_version"] = EVAL_VERSION
    atomic_write_json(eval_dir(store, name) / "metrics.json", metrics)
    return metrics


def champion_metrics(store: Store, cfg: Config, registry: Registry, gold_sha: str) -> tuple[dict | None, Path | None]:
    """The champion's GOLD metrics, recomputed when they came from another GOLD set, evaluation version or OCR
    configuration (the candidate is always evaluated with the current ones)."""
    champ = registry.champion()
    if champ is None:
        return None, None
    m = champ["metrics"]
    folder = eval_dir(store, m.get("eval_name", champ["version"]))
    ocr_now = ocr_config_hash(cfg)
    if m.get("gold_manifest_sha256") != gold_sha or m.get("eval_version") != EVAL_VERSION or \
            m.get("ocr", {}).get("ocr_config_sha256") != ocr_now or not (folder / "det_eval.npz").is_file():
        # Same GOLD, same evaluation code and the same OCR settings on both sides, or the comparison is unfair.
        m = evaluate_weights(store, cfg, Path(champ["weights_path"]), f"{champ['version']}_reeval")
        m["eval_name"] = f"{champ['version']}_reeval"
        folder = eval_dir(store, m["eval_name"])
    return m, folder


def gate_and_register(store: Store, cfg: Config, registry: Registry, weights: Path, round_id: str,
                      data_sha256: str, actor: str, notes: str = "") -> dict:
    name = f"candidate_{round_id}"
    cand = evaluate_weights(store, cfg, weights, name)
    cand["eval_name"] = name
    champ, champ_folder = champion_metrics(store, cfg, registry, cand["gold_manifest_sha256"])
    if champ is not None:
        cand_ev = DetEval.load(eval_dir(store, name) / "det_eval.npz")
        champ_ev = DetEval.load(champ_folder / "det_eval.npz")
        if cand_ev.image_ids != champ_ev.image_ids:
            raise RuntimeError("candidate and champion were evaluated on different GOLD images")
        cand["paired_gain_ci_pt"] = bootstrap_det(cand_ev, cfg.evaluate.bootstrap, cfg.seed, cfg.evaluate.conf,
                                                  other=champ_ev)
    decision = promotion_gate(cand, champ, cfg.promote)
    parent = registry.champion_version()
    record = registry.register(weights, cfg, data_sha256, round_id, cand, gold_sha256=cand["gold_manifest_sha256"],
                               parent=parent, notes=notes, train_args=store.runs_dir(round_id) / "train" / "args.yaml")
    gate = {**decision.to_dict(), "champion": parent}
    if decision.promote:
        registry.promote(record["version"], gate, actor)
    else:
        registry.reject(record["version"], gate, actor)
    result = {"version": record["version"], "promoted": decision.promote, "gate": gate,
              "metrics": {"map50_95": cand["detection"]["map50_95"], "map50": cand["detection"]["map50"],
                          "exact": cand["ocr"]["exact"]}}
    history = read_json(store.root / "rounds" / "history.json", [])
    history = [h for h in history if h["round"] != round_id] + [{
        "round": round_id, "version": record["version"], "promoted": decision.promote,
        "gain_map50_95_pt": decision.gains_pt.get("map50_95"), "gain_exact_pt": decision.gains_pt.get("exact")}]
    atomic_write_json(store.root / "rounds" / "history.json", history)
    mark(store, round_id, "gate", result)
    return result


def should_stop(history: list[dict], cfg: Config, reviewed: int) -> tuple[bool, str]:
    rr = cfg.run_round
    if reviewed >= rr.total_review_budget:
        return True, f"review budget spent ({reviewed} of {rr.total_review_budget})"
    recent = [h for h in history if h.get("gain_map50_95_pt") is not None][-rr.stop_patience_rounds:]
    if len(recent) == rr.stop_patience_rounds and all(
            max(h["gain_map50_95_pt"], h.get("gain_exact_pt") or float("-inf")) < rr.stop_gain_pt for h in recent):
        return True, (f"GOLD gain below {rr.stop_gain_pt} pt for {rr.stop_patience_rounds} rounds "
                      f"({', '.join(h['round'] for h in recent)})")
    return False, "continue"
