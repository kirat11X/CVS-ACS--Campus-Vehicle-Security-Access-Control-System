"""Review service: the only path by which a frame or a plate text becomes training data.

Every decision is appended to the hash-chained audit log (reviewer, time, frame hash, what the model proposed,
what was approved). Only `accept` / `correct` decisions on frames whose reviewer confirmed that EVERY plate is
boxed are trainable; `reject` (unusable frame) and `skip` (later) never are. A later decision on the same item
supersedes an earlier one; the log keeps both.

Auto-accept is off by default. When enabled it applies only while the Wilson 95% lower bound of the model's
precision on the random audit items is at least min_audit_precision over at least min_audit_items items.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from anpr_hitl.chainlog import ChainLog
from anpr_hitl.config import Config
from anpr_hitl.hashing import sha256_file
from anpr_hitl.labels import iou
from anpr_hitl.manifest import read_manifest
from anpr_hitl.plates import normalize_plate
from anpr_hitl.store import Store, read_jsonl

DECISIONS = ("accept", "correct", "reject", "skip")
SOURCES = ("human", "oracle", "auto")
TEXT_STATUS = ("read", "unreadable", "not_reviewed")
MATCH_IOU = 0.5  # an audit item is "model correct" when the approved boxes pair 1:1 with the proposal at this IoU


class ReviewError(ValueError):
    pass


def wilson_lower(successes: int, n: int, z: float = 1.959964) -> float:
    if n == 0:
        return 0.0
    p = successes / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def boxes_match(approved: list[dict], proposal: list[dict], min_iou: float = MATCH_IOU) -> bool:
    """Same number of boxes and a 1:1 pairing at min_iou (greedy by IoU; plates rarely overlap)."""
    if len(approved) != len(proposal):
        return False
    pairs = sorted(((iou(a["xyxy"], p["xyxy"]), i, j) for i, a in enumerate(approved) for j, p in enumerate(proposal)),
                   reverse=True)
    used_a, used_p = set(), set()
    for v, i, j in pairs:
        if v >= min_iou and i not in used_a and j not in used_p:
            used_a.add(i)
            used_p.add(j)
    return len(used_a) == len(approved)


@dataclass
class ReviewedBox:
    xyxy: tuple[float, float, float, float]
    text: str = ""
    text_status: str = "read"

    def to_dict(self) -> dict:
        return {"xyxy": [round(float(v), 2) for v in self.xyxy], "text": normalize_plate(self.text),
                "text_status": self.text_status}


class ReviewService:
    def __init__(self, store: Store, cfg: Config):
        self.store, self.cfg = store, cfg
        self.log = ChainLog(store.audit_log)

    # ---------------------------------------------------------------- queue

    def queue(self, round_id: str) -> list[dict]:
        return sorted(read_manifest(self.store.queue_path(round_id)), key=lambda it: it["rank"])

    def predictions(self, round_id: str) -> dict[str, dict]:
        rows = read_jsonl(self.store.predictions_dir(round_id) / "predictions.jsonl")
        return {r["frame_id"]: r for r in rows}

    def decisions(self) -> dict[str, dict]:
        """Latest decision per item id (the log is replayed in order)."""
        latest = {}
        for e in self.log.entries():
            if e.get("event") == "decision":
                latest[e["item_id"]] = e
        return latest

    def decided_frames(self) -> set[str]:
        return {e["frame_id"] for e in self.decisions().values() if e["decision"] != "skip"}

    def pending(self, round_id: str) -> list[dict]:
        """Undecided items in rank order; skipped items go to the end."""
        latest = self.decisions()
        todo = [it for it in self.queue(round_id) if latest.get(it["item_id"], {}).get("decision", "skip") == "skip"]
        return sorted(todo, key=lambda it: (it["item_id"] in latest, it["rank"]))

    # ---------------------------------------------------------------- decisions

    def reviewer_name(self, explicit: str | None = None) -> str:
        name = (explicit or os.environ.get(self.cfg.review.reviewer_env, "")).strip()
        if not name:
            raise ReviewError(f"reviewer name required (--reviewer or ${self.cfg.review.reviewer_env})")
        return name

    def submit(self, round_id: str, item_id: str, decision: str, boxes: list[ReviewedBox], all_plates_boxed: bool,
               reviewer: str, source: str = "human", seconds: float | None = None, notes: str = "") -> dict:
        if decision not in DECISIONS:
            raise ReviewError(f"decision must be one of {DECISIONS}")
        if source not in SOURCES:
            raise ReviewError(f"source must be one of {SOURCES}")
        if not reviewer.strip():
            raise ReviewError("reviewer name required")
        item = next((it for it in self.queue(round_id) if it["item_id"] == item_id), None)
        if item is None:
            raise ReviewError(f"{item_id} is not in the {round_id} queue")
        pred = self.predictions(round_id).get(item["frame_id"])
        if pred is None:
            raise ReviewError(f"no prediction row for {item['frame_id']}")
        frame = self.store.root / item["path"]
        frame_sha = sha256_file(frame)
        if pred.get("sha256") and pred["sha256"] != frame_sha:
            raise ReviewError(f"{item['frame_id']} changed on disk since it was predicted")
        w, h = pred["width"], pred["height"]
        clean = []
        for b in boxes:
            x1, y1, x2, y2 = b.xyxy
            if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                raise ReviewError(f"box {b.xyxy} is outside the {w}x{h} frame or inverted")
            if b.text_status not in TEXT_STATUS:
                raise ReviewError(f"text_status must be one of {TEXT_STATUS}")
            if b.text_status == "read" and not normalize_plate(b.text):
                raise ReviewError("a box marked 'read' needs its plate text (or mark it unreadable)")
            clean.append(b.to_dict())
        proposal = [{"xyxy": p["xyxy"], "conf": p["conf"], "text": p["ocr"]["text"]} for p in pred["boxes"]]
        if decision == "accept":
            if not boxes_match(clean, proposal, 0.999) or any(
                    c["text"] != p["text"] for c, p in zip(sorted(clean, key=lambda c: c["xyxy"]),
                                                          sorted(proposal, key=lambda p: p["xyxy"]), strict=True)
                    if c["text_status"] == "read"):
                raise ReviewError("'accept' means the proposal is right as it is; use 'correct' for any change")
        if decision in ("reject", "skip"):
            clean = []
        return self.log.append({
            "event": "decision", "item_id": item_id, "round": round_id, "frame_id": item["frame_id"],
            "frame_sha256": frame_sha, "decision": decision, "boxes": clean, "all_plates_boxed": bool(all_plates_boxed),
            "reviewer": reviewer.strip(), "source": source, "audit": bool(item.get("audit")),
            "proposal": proposal, "model": pred.get("model"), "seconds": seconds, "notes": notes,
            "model_correct": decision == "accept" or (decision == "correct" and boxes_match(clean, proposal)
                                                      and source == "oracle"),
        })

    # ---------------------------------------------------------------- training gate

    def audit_stats(self) -> dict:
        """Model precision on the random audit items (frame level: proposal approved without box changes)."""
        audited = [e for e in self.decisions().values()
                   if e["audit"] and e["decision"] in ("accept", "correct") and e["source"] in ("human", "oracle")]
        ok = sum(bool(e["model_correct"]) for e in audited)
        return {"n": len(audited), "model_correct": ok, "precision": ok / len(audited) if audited else None,
                "wilson_lower": round(wilson_lower(ok, len(audited)), 4)}

    def auto_accept_allowed(self) -> tuple[bool, str]:
        aa = self.cfg.review.auto_accept
        if not aa.enabled:
            return False, "auto-accept is disabled in config.yaml"
        stats = self.audit_stats()
        if stats["n"] < aa.min_audit_items:
            return False, f"only {stats['n']} audited items (< {aa.min_audit_items})"
        if stats["wilson_lower"] < aa.min_audit_precision:
            return False, f"audit precision lower bound {stats['wilson_lower']:.3f} < {aa.min_audit_precision}"
        return True, f"audit precision lower bound {stats['wilson_lower']:.3f} over {stats['n']} items"

    def trainable(self, rounds: set[str] | None = None) -> list[dict]:
        """Latest decisions that may enter training: accept / correct, every plate boxed, frame unchanged.

        Auto-accepted items count only while the auto-accept gate is open.
        """
        auto_ok = self.auto_accept_allowed()[0]
        paths: dict[str, dict[str, str]] = {}
        out = []
        for e in self.decisions().values():
            if rounds is not None and e["round"] not in rounds:
                continue
            if e["decision"] not in ("accept", "correct") or not e["all_plates_boxed"]:
                continue
            if e["source"] == "auto" and not auto_ok:
                continue
            if e["round"] not in paths:
                paths[e["round"]] = {it["item_id"]: it["path"] for it in self.queue(e["round"])}
            frame = self.store.root / paths[e["round"]][e["item_id"]]
            if not frame.is_file() or sha256_file(frame) != e["frame_sha256"]:
                continue  # the approved pixels are gone or changed: never train on a different image
            out.append({**e, "path": str(frame.relative_to(self.store.root))})
        return out

    def summary(self, round_id: str) -> dict:
        queue = self.queue(round_id)
        latest = self.decisions()
        counts = {d: 0 for d in DECISIONS}
        for it in queue:
            e = latest.get(it["item_id"])
            if e:
                counts[e["decision"]] += 1
        return {"round": round_id, "queued": len(queue), **counts,
                "pending": len(queue) - sum(v for k, v in counts.items() if k != "skip"),
                "incomplete_frames": sum(1 for it in queue if (e := latest.get(it["item_id"]))
                                         and e["decision"] in ("accept", "correct") and not e["all_plates_boxed"])}
