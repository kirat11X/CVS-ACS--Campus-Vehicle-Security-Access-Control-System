"""Assemble a round's detector training set from reviewed frames only, plus replay of earlier data.

train = this round's trainable decisions (human / oracle boxes; never model output)
      + replay: earlier data (bootstrap seed + earlier rounds' trainable decisions), sampled deterministically so
        it is at least replay_fraction of the training images
val   = bootstrap val (+ PEC val frames once they are labelled)
Before anything is written, every image is checked against GOLD (byte-identical or dHash within
leakage_max_bits) and train against val; any hit stops the round.
"""

from __future__ import annotations

import math
import random

from anpr_hitl.config import Config
from anpr_hitl.hashing import image_dhash, sha256_file
from anpr_hitl.labels import read_yolo_labels, write_yolo_labels, xyxy_to_yolo
from anpr_hitl.manifest import read_manifest, write_manifest
from anpr_hitl.review.service import ReviewService
from anpr_hitl.splits import leakage_check
from anpr_hitl.store import Store, atomic_write_json, atomic_write_text


class LeakageError(RuntimeError):
    pass


def replay_count(n_new: int, n_old: int, fraction: float) -> int:
    """Smallest replay size making replay / (new + replay) >= fraction (capped by the old data available)."""
    if fraction <= 0 or n_old == 0:
        return 0
    if n_new == 0:
        return n_old
    return min(n_old, math.ceil(n_new * fraction / (1 - fraction) - 1e-9))


def _bootstrap_rows(store: Store, split: str) -> list[dict]:
    root = store.bootstrap_dir / "detector"
    rows = []
    for r in read_manifest(root / "manifest.jsonl"):
        if r["split"] != split:
            continue
        rows.append({"key": f"{split}/{r['image_id']}", "image": store.root / r["path"],
                     "label_file": root / split / "labels" / f"{r['image_id']}.txt",
                     "dhash": int(r["dhash"], 16) if r.get("dhash") else None, "origin": f"bootstrap:{split}"})
    return rows


def _decision_rows(decisions: list[dict], store: Store) -> list[dict]:
    rows = []
    for e in decisions:
        image = store.root / e["path"]
        rows.append({"key": e["frame_id"], "image": image, "boxes": [b["xyxy"] for b in e["boxes"]],
                     "dhash": image_dhash(image), "origin": f"review:{e['round']}:{e['source']}",
                     "decision_hash": e["hash"]})
    return rows


def gold_hashes(store: Store) -> tuple[set[str], list[tuple[str, int | None]]]:
    rows = read_manifest(store.gold_dir / "det" / "manifest.jsonl")
    return {r["sha256"] for r in rows}, [(r["image_id"], int(r["dhash"], 16) if r.get("dhash") else None) for r in rows]


def assemble(store: Store, cfg: Config, round_id: str, service: ReviewService | None = None,
             earlier_rounds: list[str] | None = None, force: bool = False) -> dict:
    out = store.dataset_dir(round_id)
    if (out / "manifest.jsonl").is_file():
        if not force:
            raise FileExistsError(f"{out} is already assembled (pass force=True to rebuild it from the audit log)")
        for split in ("train", "val"):  # derived files only: symlinks and label files written below
            for path in sorted((out / split).rglob("*"), reverse=True):
                path.rmdir() if path.is_dir() and not path.is_symlink() else path.unlink()
    service = service or ReviewService(store, cfg)
    new = _decision_rows(service.trainable({round_id}), store)
    earlier = set(earlier_rounds or [])
    old = _bootstrap_rows(store, "seed") + _decision_rows(service.trainable(earlier) if earlier else [], store)
    n_replay = replay_count(len(new), len(old), cfg.train.replay_fraction)
    rng = random.Random(f"{cfg.seed}:{round_id}:replay")
    replay = sorted(rng.sample(sorted(old, key=lambda r: r["key"]), n_replay), key=lambda r: r["key"])
    train = new + replay
    val = _bootstrap_rows(store, "val")
    if not new:
        raise RuntimeError(f"round {round_id} has no trainable reviewed frames")

    gold_sha, gold_dh = gold_hashes(store)
    for row in train + val:
        row["sha256"] = sha256_file(row["image"])
    byte_leaks = [r["key"] for r in train + val if r["sha256"] in gold_sha]
    if byte_leaks:
        raise LeakageError(f"{len(byte_leaks)} training/val images are byte-identical to GOLD: {byte_leaks[:3]}")
    leaks = leakage_check({"train": [(r["key"], r["dhash"]) for r in train],
                           "val": [(r["key"], r["dhash"]) for r in val], "gold": gold_dh}, cfg.splits.leakage_max_bits)
    if leaks:
        raise LeakageError(f"{len(leaks)} near-duplicates across train/val/GOLD, e.g. {leaks[:3]}")

    manifest = []
    for split, rows in (("train", train), ("val", val)):
        img_dir, lbl_dir = out / split / "images", out / split / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        for i, row in enumerate(rows):
            stem = f"{i:05d}_{row['key'].replace('/', '__')}"
            dst = img_dir / f"{stem}{row['image'].suffix.lower()}"
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(row["image"].resolve())
            label = lbl_dir / f"{stem}.txt"
            if "boxes" in row:
                from PIL import Image

                with Image.open(row["image"]) as img:
                    w, h = img.size
                write_yolo_labels(label, [(0, *y) for b in row["boxes"] if (y := xyxy_to_yolo(b, w, h))])
            else:
                write_yolo_labels(label, read_yolo_labels(row["label_file"]))
            manifest.append({"split": split, "stem": stem, "key": row["key"], "origin": row["origin"],
                             "sha256": row["sha256"], "label_sha256": sha256_file(label),
                             "decision_hash": row.get("decision_hash")})
    data_yaml = out / "data.yaml"
    atomic_write_text(data_yaml, f"path: {out}\ntrain: train/images\nval: val/images\nnames:\n  0: {cfg.class_names[0]}\n")
    data_hash = write_manifest(out / "manifest.jsonl", manifest)
    summary = {"round": round_id, "train_images": len(train), "new_reviewed": len(new), "replay": len(replay),
               "replay_share": round(len(replay) / len(train), 4), "val_images": len(val),
               "replay_pool": len(old), "gold_byte_leaks": 0, "near_duplicate_leaks": 0,
               "data_manifest_sha256": data_hash, "data_yaml": str(data_yaml)}
    atomic_write_json(out / "summary.json", summary)
    return summary
