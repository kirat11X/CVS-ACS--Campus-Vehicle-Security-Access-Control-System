"""Select frames for review.

1. Audit: audit_fraction of the round's budget is drawn uniformly at random from all candidates. These items
   measure the model without selection bias (the auto-accept gate and the precision estimate use only them).
2. The rest of the budget goes to the highest-scoring frames: score = sum of the weights of the signals present
   (low confidence / near miss, track or engine disagreement, format failure, low character confidence, rare
   slice). Ties go to the frame whose most uncertain box is closest to 0.5, then to a stable hash.
3. Diversity: a frame within leakage_max_bits dHash of an already selected frame is skipped, and one group
   (video / site) may fill at most max_group_fraction of the budget.
Only pool frames are candidates; val and GOLD frames are never selected, and decided frames are not re-selected.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from pathlib import Path

from anpr_hitl.config import Config
from anpr_hitl.hashing import hamming
from anpr_hitl.manifest import write_manifest
from anpr_hitl.store import atomic_write_json

SIGNALS = {
    "low_confidence": ("low_confidence", "near_miss"),
    "track_disagreement": ("track_disagreement", "engine_disagreement"),
    "regex_failure": ("regex_failure",),
    "low_char_conf": ("low_char_conf",),
}


def rare_states(rows: list[dict], max_count: int = 3) -> set[str]:
    """State codes read on at most max_count frames of the pool (a weak signal: reads can be wrong)."""
    counts = Counter()
    for r in rows:
        for b in r.get("boxes", []):
            text = b["ocr"]["text"]
            if b["check"]["format"] == "standard":
                counts[text[:2]] += 1
    return {s for s, n in counts.items() if n <= max_count}


def score_frame(row: dict, cfg: Config, rare: set[str]) -> tuple[float, list[str]]:
    flags = set(row.get("flags", []))
    reasons = [name for name, members in SIGNALS.items() if flags & set(members)]
    states = {b["ocr"]["text"][:2] for b in row.get("boxes", []) if b["check"]["format"] == "standard"}
    if "night" in flags or states & rare:
        reasons.append("rare_slice")
    weights = cfg.select.weights.model_dump()
    return sum(weights[r] for r in reasons), reasons


def _uncertainty(row: dict) -> float:
    confs = [b["conf"] for b in row.get("boxes", [])] + [b["conf"] for b in row.get("near_misses", [])]
    return min((abs(c - 0.5) for c in confs), default=0.5)


def _stable(round_id: str, frame_id: str) -> str:
    return hashlib.sha256(f"{round_id}:{frame_id}".encode()).hexdigest()


def select_frames(rows: list[dict], cfg: Config, round_id: str, decided: set[str], reviewed_total: int,
                  budget: int | None = None) -> dict:
    """Returns {'items': [...], 'summary': {...}}; deterministic for a given round id and seed."""
    s = cfg.select
    budget = s.review_budget if budget is None else budget
    remaining_total = cfg.run_round.total_review_budget - reviewed_total
    budget = max(0, min(budget, remaining_total))
    candidates = [r for r in rows if r.get("split") == "pool" and r["frame_id"] not in decided]
    candidates.sort(key=lambda r: r["frame_id"])
    rare = rare_states(candidates)
    scored = {}
    for r in candidates:
        scored[r["frame_id"]] = score_frame(r, cfg, rare)

    n_audit = min(len(candidates), round(budget * s.audit_fraction))
    rng = random.Random(f"{cfg.seed}:{round_id}:audit")
    audit = rng.sample(candidates, n_audit) if n_audit else []
    chosen: list[tuple[dict, bool]] = [(r, True) for r in sorted(audit, key=lambda r: r["frame_id"])]
    chosen_ids = {r["frame_id"] for r in audit}
    group_cap = max(1, math.ceil(budget * s.max_group_fraction))
    groups = Counter(r.get("group") for r in audit)
    hashes = [int(r["dhash"], 16) for r in audit if r.get("dhash")]

    ranked = sorted((r for r in candidates if r["frame_id"] not in chosen_ids),
                    key=lambda r: (-scored[r["frame_id"]][0], _uncertainty(r), _stable(round_id, r["frame_id"])))
    skipped_dup = skipped_group = 0
    for r in ranked:
        if len(chosen) >= budget:
            break
        if groups[r.get("group")] >= group_cap:
            skipped_group += 1
            continue
        h = int(r["dhash"], 16) if r.get("dhash") else None
        if h is not None and any(hamming(h, k) <= cfg.splits.leakage_max_bits for k in hashes):
            skipped_dup += 1
            continue
        chosen.append((r, False))
        groups[r.get("group")] += 1
        if h is not None:
            hashes.append(h)

    items = []
    for rank, (r, is_audit) in enumerate(chosen):
        score, reasons = scored[r["frame_id"]]
        items.append({"item_id": f"{round_id}:{r['frame_id']}", "round": round_id, "frame_id": r["frame_id"],
                      "path": r["path"], "kind": r.get("kind"), "video_id": r.get("video_id"), "group": r.get("group"),
                      "split": r["split"], "audit": is_audit, "score": round(score, 3), "reasons": reasons,
                      "rank": rank, "oracle": bool(r.get("oracle_label"))})
    reason_counts = Counter(x for it in items for x in it["reasons"])
    summary = {"round": round_id, "candidates": len(candidates), "budget": budget, "selected": len(items),
               "audit": sum(it["audit"] for it in items), "skipped_near_duplicate": skipped_dup,
               "skipped_group_cap": skipped_group, "reasons": dict(reason_counts),
               "remaining_total_budget": remaining_total - len(items)}
    return {"items": items, "summary": summary}


def write_queue(round_dir: Path, selection: dict) -> str:
    queue_hash = write_manifest(round_dir / "queue.jsonl", selection["items"])
    atomic_write_json(round_dir / "queue_summary.json", {**selection["summary"], "queue_sha256": queue_hash})
    return queue_hash
