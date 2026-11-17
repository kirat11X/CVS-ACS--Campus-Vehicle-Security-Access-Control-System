"""Bootstrap data from licence-cleared, human-labelled public Indian plate sets.

Splits are made per near-duplicate group (Roboflow source stem + EXIF-upright dHash within
DETECTOR_NEAR_DUP_BITS, union-find) BEFORE any image is used:
  seed  round-0 training data
  pool  the simulated reviewer's pool: its human labels are stored apart (oracle_labels/) and are only
        revealed for the frames a round selects
  val   validation during training
  gold  provisional GOLD: frozen copies + SHA-256, never trained on, never auto-labelled. Public data,
        so it is NOT PEC footage and not split by video; replace it once >= 10 labelled PEC videos exist.
OCR GOLD: held-out human-labelled plate crops (texts merged across near-identical crops).
"""

from __future__ import annotations

import csv
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageOps

from anpr_hitl.config import PACKAGE_ROOT, Config
from anpr_hitl.hashing import image_dhash, sha256_file
from anpr_hitl.labels import write_yolo_labels
from anpr_hitl.manifest import read_manifest, write_manifest
from anpr_hitl.plates import check_plate
from anpr_hitl.splits import leakage_check
from anpr_hitl.store import Store, atomic_write_json, atomic_write_text

TRACK_A = PACKAGE_ROOT.parent / "finetune" / "track_a"
DETECTOR_RATIOS = {"gold": 0.22, "val": 0.10, "seed": 0.30, "pool": 0.38}
OCR_GOLD_FRACTION = 0.20
MIN_GOLD_PLATES = 500


def _prep():
    sys.path.insert(0, str(TRACK_A))
    import prepare_plate_training_sets as prep  # noqa: PLC0415 - research script, not a package

    return prep


def assign_groups(groups: list, ratios: dict[str, float], seed: int) -> dict:
    """Shuffle groups deterministically and cut them by cumulative ratio (order: gold, val, seed, pool)."""
    ordered = sorted(groups, key=str)
    random.Random(seed).shuffle(ordered)
    cuts, total, out = [], 0.0, {}
    for name in ("gold", "val", "seed", "pool"):
        total += ratios[name]
        cuts.append((name, round(total * len(ordered))))
    start = 0
    for name, end in cuts:
        for g in ordered[start:end]:
            out[g] = name
        start = end
    for g in ordered[start:]:
        out[g] = "pool"
    return out


def _write_image(src: Path, dst: Path, copy: bool) -> bool:
    """Link (or copy, for frozen GOLD) an image; EXIF-rotated photos are written upright. True if rewritten."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    with Image.open(src) as img:
        if img.getexif().get(274, 1) in (0, 1):
            if copy:
                shutil.copyfile(src, dst)
            else:
                dst.symlink_to(Path(src).resolve())
            return False
        upright = ImageOps.exif_transpose(img).convert("RGB")
    upright.save(dst.with_suffix(".jpg"), quality=95)
    return True


def build_detector_sets(store: Store, cfg: Config, ratios: dict[str, float] | None = None) -> dict:
    prep = _prep()
    ratios = ratios or DETECTOR_RATIOS
    records = []
    for name, (_, rel) in prep.DETECTOR_SOURCES.items():
        recs, _ = prep.detector_records(name, prep.ROOT / rel)
        records += recs
    uf = prep.UnionFind()
    hashes = []
    for rec in records:
        uf.find(rec["key"])
        rec["dhash"] = prep.image_hash(rec["image"])
        hashes.append((rec["key"], rec["dhash"]))
    prep.merge_near_duplicates(uf, hashes, prep.DETECTOR_NEAR_DUP_BITS)
    split_of = assign_groups(list({uf.find(r["key"]) for r in records}), ratios, cfg.seed)

    gold_plates = sum(len(r["boxes"]) for r in records if split_of[uf.find(r["key"])] == "gold")
    if gold_plates < MIN_GOLD_PLATES:
        raise RuntimeError(f"provisional GOLD would hold {gold_plates} plates (< {MIN_GOLD_PLATES}); raise its ratio")

    root = store.bootstrap_dir / "detector"
    gold_root = store.gold_dir / "det"
    for path in (root, gold_root):
        if path.exists() and any(path.iterdir()):
            raise SystemExit(f"{path} already exists; bootstrap data is built once (delete it deliberately to rebuild)")
    rows, counts = [], defaultdict(Counter)
    for i, rec in enumerate(records):
        split = split_of[uf.find(rec["key"])]
        stem = f"{rec['source']}__{i:05d}"
        if split == "gold":
            img_dir, lbl_dir = gold_root / "images", gold_root / "labels"
        else:
            img_dir = root / split / "images"
            lbl_dir = root / split / ("oracle_labels" if split == "pool" else "labels")
        dst = img_dir / f"{stem}{rec['image'].suffix.lower()}"
        rewritten = _write_image(rec["image"], dst, copy=split == "gold")
        final = dst.with_suffix(".jpg") if rewritten else dst
        label = lbl_dir / f"{stem}.txt"
        write_yolo_labels(label, [(0, *b) for b in rec["boxes"]])
        rows.append({"image_id": stem, "split": split, "source": rec["source"], "group": str(uf.find(rec["key"])),
                     "path": str(final.relative_to(store.root)), "boxes": len(rec["boxes"]),
                     "dhash": f"{rec['dhash']:016x}" if rec["dhash"] is not None else None,
                     "sha256": sha256_file(final) if split == "gold" else None,
                     "label_sha256": sha256_file(label) if split == "gold" else None, "exif_rewritten": rewritten})
        counts[split][rec["source"]] += 1

    names = "names:\n  0: license_plate\n"
    atomic_write_text(root / "seed_data.yaml", f"path: {root}\ntrain: seed/images\nval: val/images\n{names}")
    atomic_write_text(gold_root / "data.yaml", f"path: {gold_root}\ntrain: images\nval: images\ntest: images\n{names}")
    data_hash = write_manifest(root / "manifest.jsonl", [r for r in rows if r["split"] != "gold"])
    gold_rows = [r for r in rows if r["split"] == "gold"]
    gold_hash = write_manifest(gold_root / "manifest.jsonl", gold_rows)

    by_split = {s: [(r["image_id"], int(r["dhash"], 16) if r["dhash"] else None) for r in rows if r["split"] == s]
                for s in ("seed", "pool", "val", "gold")}
    leaks = leakage_check(by_split, cfg.splits.leakage_max_bits)
    summary = {
        "ratios": ratios, "seed": cfg.seed, "groups": len(split_of),
        "images": {s: sum(c.values()) for s, c in counts.items()},
        "plates": {s: sum(r["boxes"] for r in rows if r["split"] == s) for s in ("seed", "pool", "val", "gold")},
        "per_source": {s: dict(c) for s, c in counts.items()},
        "cross_split_near_duplicates": len(leaks), "data_manifest_sha256": data_hash, "gold_manifest_sha256": gold_hash,
        "gold_note": "provisional: public licence-cleared Indian data, not PEC footage, not split by video",
    }
    atomic_write_json(root / "summary.json", summary)
    atomic_write_json(gold_root / "gold.json", {"kind": "detector", "frozen": True, "manifest_sha256": gold_hash,
                                                "plates": summary["plates"]["gold"], "note": summary["gold_note"]})
    if leaks:
        raise RuntimeError(f"{len(leaks)} cross-split near-duplicates in the bootstrap split: {leaks[:3]}")
    return summary


def _ocr_groups(prep, cfg: Config) -> tuple[list[dict], list, set]:
    """OCR records, their near-duplicate group ids (text + 2-bit dHash), and the GOLD groups (deterministic)."""
    records = []
    for rec in prep.ocr_records():
        text = prep.norm_plate(rec["raw"])
        if rec["image"].is_file() and prep.OCR_TEXT.match(text):
            records.append({**rec, "text": text})
    uf = prep.UnionFind()
    hashes = []
    for rec in records:
        uf.find(rec["text"])
        rec["dhash"] = image_dhash(rec["image"])
        hashes.append((rec["text"], rec["dhash"]))
    prep.merge_near_duplicates(uf, hashes, prep.OCR_NEAR_DUP_BITS)
    for rec in records:
        rec["group"] = uf.find(rec["text"])
    groups = sorted({r["group"] for r in records}, key=str)
    random.Random(cfg.seed).shuffle(groups)
    return records, groups, set(groups[: round(len(groups) * OCR_GOLD_FRACTION)])


def build_ocr_gold(store: Store, cfg: Config) -> dict:
    prep = _prep()
    records, _, gold_groups = _ocr_groups(prep, cfg)
    out = store.gold_dir / "ocr"
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} already exists; OCR GOLD is built once")
    rows = []
    for i, rec in enumerate(r for r in records if r["group"] in gold_groups):
        dst = out / "crops" / f"{rec['source']}__{i:05d}{rec['image'].suffix.lower()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rec["image"], dst)
        check = check_plate(rec["text"])
        rows.append({"crop_id": dst.stem, "path": str(dst.relative_to(store.root)), "text": rec["text"],
                     "source": rec["source"], "format_valid": check.regex_valid, "sha256": sha256_file(dst)})
    with open(out / "gold.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["crop_id"]))
    gold_hash = write_manifest(out / "manifest.jsonl", rows)
    summary = {"crops": len(rows), "unique_texts": len({r["text"] for r in rows}),
               "format_invalid_labels": sum(not r["format_valid"] for r in rows), "manifest_sha256": gold_hash,
               "note": "provisional: public licence-cleared Indian crops; all labels are scored (format-invalid ones are flagged, not excluded)"}
    atomic_write_json(out / "gold.json", {"kind": "ocr", "frozen": True, **summary})
    return summary


def build_ocr_dev(store: Store, cfg: Config, size: int = 600) -> dict:
    """OCR development set for choosing an engine or its settings: one crop per non-GOLD group, never GOLD.

    Choosing on GOLD would bias every later GOLD number, so engine comparisons are made here.
    """
    prep = _prep()
    records, groups, gold_groups = _ocr_groups(prep, cfg)
    dev_groups = [g for g in groups if g not in gold_groups][:size]  # `groups` is already seed-shuffled
    first = {}
    for rec in records:
        first.setdefault(rec["group"], rec)
    gold_rows = read_manifest(store.gold_dir / "ocr" / "manifest.jsonl")
    gold_sha = {r["sha256"] for r in gold_rows}
    gold_hashes = [(r["crop_id"], image_dhash(store.root / r["path"])) for r in gold_rows]
    out = store.bootstrap_dir / "ocr_dev"
    rows = []
    for i, group in enumerate(dev_groups):
        rec = first[group]
        dst = out / "crops" / f"{rec['source']}__dev{i:05d}{rec['image'].suffix.lower()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(rec["image"], dst)
        rows.append({"crop_id": dst.stem, "path": str(dst.relative_to(store.root)), "text": rec["text"],
                     "source": rec["source"], "format_valid": check_plate(rec["text"]).regex_valid,
                     "sha256": sha256_file(dst), "dhash": rec["dhash"]})
    if gold_sha & {r["sha256"] for r in rows}:
        raise RuntimeError("an OCR dev crop is byte-identical to an OCR GOLD crop")
    leaks = leakage_check({"dev": [(r["crop_id"], r["dhash"]) for r in rows], "gold": gold_hashes},
                          prep.OCR_NEAR_DUP_BITS)
    if leaks:
        raise RuntimeError(f"{len(leaks)} OCR dev crops are near-duplicates of GOLD crops: {leaks[:3]}")
    for r in rows:
        r.pop("dhash")
    data_hash = write_manifest(out / "manifest.jsonl", rows)
    summary = {"crops": len(rows), "manifest_sha256": data_hash, "gold_near_duplicates": 0,
               "note": "one crop per non-GOLD near-duplicate group; for engine/setting choices only"}
    atomic_write_json(out / "summary.json", summary)
    return summary
