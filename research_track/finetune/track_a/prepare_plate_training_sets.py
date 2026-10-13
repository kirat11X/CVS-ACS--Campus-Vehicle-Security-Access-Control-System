"""Build the merged Indian plate detector set and the OCR crop set from licence-cleared downloads.

    python prepare_plate_training_sets.py detector --output ~/ml-assets/campus/datasets/prepared/plate_det_in_v1
    python prepare_plate_training_sets.py ocr --output ~/ml-assets/campus/datasets/prepared/ocr_in_v1

Only sources with an explicit permissive licence are used (CC0, CC BY 4.0, MIT, Apache-2.0); "unknown",
NC and ND sets are excluded. Splits are grouped so near-identical images never straddle splits:
Roboflow augmentations of one source image, near-identical images across datasets (dHash of the upright
image within DETECTOR_NEAR_DUP_BITS), and (for OCR) every crop of the same plate text. Images are
symlinked, not copied.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_plate_datasets import IMAGE_EXTS, dhash, label_for, norm_plate, parse_yolo  # noqa: E402

ROOT = Path.home() / "ml-assets" / "campus" / "datasets"
CROP_LIKE_AREA = 0.6  # a box covering this much of the frame means the "scene" is really a plate crop
# Images whose 64-bit dHash differs by at most this many bits share a group. Measured on plate_det_in_v1
# (audit 2026-10-13): pairs at 1-2 bits are re-exports/re-encodes of one photo, 4-6 bits are frames of one
# fixed-camera scene, and 8 bits already chains unrelated images into a 162-image component.
DETECTOR_NEAR_DUP_BITS = 6
# Plate crops all look alike at 9x8, so OCR uses a tighter bound. Measured on ocr_in_v1: crop pairs within
# 2 bits carry the same text or a <=2-edit label typo (1648 of 1651 pairs); at 3-4 bits different plates appear.
OCR_NEAR_DUP_BITS = 2

DETECTOR_SOURCES = {
    # name: (licence, path relative to ROOT)
    "IN-02": ("CC0-1.0", "IN-02/extracted"),
    "rf-9oobq": ("CC BY 4.0", "ROBOFLOW-indian-number-plates-9oobq/v7"),
    "rf-nrsft": ("CC BY 4.0", "ROBOFLOW-indian-number-plates-nrsft/v1"),
    "rf-wqbsq": ("CC BY 4.0", "ROBOFLOW-indian-number-plates-wqbsq/v2"),
    "rf-5lir1": ("CC BY 4.0", "ROBOFLOW-indian-plates-5lir1/v1767178852"),
    "rf-ffxsw": ("CC BY 4.0", "ROBOFLOW-number-plates-ffxsw/v1"),
    "rf-rvmml": ("CC BY 4.0", "ROBOFLOW-vehicle-number-plates-rvmml/v1"),
    "kg-paneraghanshyam": ("Apache-2.0", "KAGGLE-paneraghanshyam-gujarat-vehicle-number-plates-yolo-ready"),
    "kg-deepakat002": ("CC0-1.0", "KAGGLE-deepakat002-indian-vehicle-number-plate-yolo-annotation"),
    "kg-ankitbarai507": ("CC0-1.0", "KAGGLE-ankitbarai507-indian-vehicle-license-plates"),
    "kg-dataclusterlabs": ("CC0-1.0", "KAGGLE-dataclusterlabs-indian-number-plates-dataset"),
}
# The 2026-10-09 baseline detector trained on IN-02 JPGs; keep them (and their duplicates) out of test.
TRAIN_ONLY_SOURCES = {"IN-02"}

OCR_SOURCES = {
    "kg-avinash-6": ("Apache-2.0", "KAGGLE-avinashjadjasadf-indian-vehicle-number-plate-dataset-6"),
    "kg-kp00011": ("MIT", "KAGGLE-kp00011-indian-vehical-number-plate-ocr-labeled-dataset"),
}
OCR_TEXT = re.compile(r"^[A-Z0-9]{4,11}$")


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b) -> None:
        self.parent[self.find(a)] = self.find(b)


def source_stem(path: Path) -> str:
    """Strip Roboflow's export suffix so augmented copies of one upload share a key."""
    stem = re.sub(r"\.rf\.[0-9a-f]+$", "", path.stem)
    return re.sub(r"_(jpe?g|png|bmp|webp)$", "", stem, flags=re.IGNORECASE)


def image_hash(path: Path) -> int | None:
    """dHash of the image as it is written to the split (EXIF orientation applied)."""
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as img:
            return dhash(ImageOps.exif_transpose(img))
    except Exception:  # unreadable image: no cross-source grouping, still kept in its own group
        return None


def merge_near_duplicates(uf: UnionFind, keyed_hashes: list, max_bits: int) -> None:
    """Union the keys of images whose dHashes differ by at most max_bits (None hashes are skipped)."""
    import numpy as np

    pairs = [(key, h) for key, h in keyed_hashes if h is not None]
    if not pairs:
        return
    keys = [key for key, _ in pairs]
    hashes = np.array([h for _, h in pairs], dtype=np.uint64)
    m1, m2, m4 = np.uint64(0x5555555555555555), np.uint64(0x3333333333333333), np.uint64(0x0F0F0F0F0F0F0F0F)
    for i in range(len(hashes) - 1):
        x = np.bitwise_xor(hashes[i + 1:], hashes[i])
        x = x - ((x >> np.uint64(1)) & m1)
        x = (x & m2) + ((x >> np.uint64(2)) & m2)
        bits = (((x + (x >> np.uint64(4))) & m4) * np.uint64(0x0101010101010101)) >> np.uint64(56)
        for j in np.nonzero(bits <= max_bits)[0]:
            uf.union(keys[i], keys[i + 1 + int(j)])


def grouped_split(items: list, group_of, ratios: tuple[float, float], seed: int, forced: dict | None = None) -> dict:
    """Assign each group to train/val/test by shuffled group order; `forced` pins groups to a split."""
    groups = sorted({group_of(item) for item in items}, key=str)
    random.Random(seed).shuffle(groups)
    forced = forced or {}
    free = [g for g in groups if g not in forced]
    cut, val_cut = int(len(free) * ratios[0]), int(len(free) * (ratios[0] + ratios[1]))
    split = {g: ("train" if i < cut else "val" if i < val_cut else "test") for i, g in enumerate(free)}
    split.update(forced)
    return split


def link(src: Path, dst: Path) -> bool:
    """Symlink src to dst; EXIF-rotated photos are written upright instead. Returns True if rewritten.

    Annotators draw on the upright view (VOC sizes are the rotated dims), so baking the rotation in keeps
    labels and pixels in one frame for every reader, not just EXIF-aware ones.
    """
    from PIL import Image, ImageOps

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    with Image.open(src) as img:
        if img.getexif().get(274, 1) in (0, 1):
            dst.symlink_to(src.resolve())
            return False
        upright = ImageOps.exif_transpose(img).convert("RGB")
    upright.thumbnail((1280, 1280))
    upright.save(dst.with_suffix(".jpg"), quality=95)
    return True


# ---------------------------------------------------------------- detector


def detector_records(name: str, root: Path) -> tuple[list[dict], Counter]:
    """Full-scene images with plate boxes as YOLO (cx, cy, w, h); all plate classes collapse to 0."""
    dropped = Counter()
    voc = {p.stem: p for p in root.rglob("*.xml") if b"<annotation" in p.read_bytes()[:500]}
    records = []
    for image in sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTS):
        if name == "IN-02" and image.suffix.lower() != ".jpg":
            dropped["in02_png_crop"] += 1  # IN-02 PNGs are pre-cropped plates (PREREQ_REPORT anomaly 4)
            continue
        boxes = None
        label = label_for(image)
        if label.is_file():
            boxes = [b[1:] for b in parse_yolo(label) or []]
        elif image.stem in voc:
            tree = ET.parse(voc[image.stem]).getroot()
            w = float(tree.findtext("size/width") or 0)
            h = float(tree.findtext("size/height") or 0)
            if not w or not h:
                from PIL import Image

                with Image.open(image) as img:
                    w, h = img.size
            boxes = []
            for obj in tree.iter("object"):
                bb = obj.find("bndbox")
                if bb is not None:
                    x0, y0, x1, y1 = (float(bb.findtext(k, "0")) for k in ("xmin", "ymin", "xmax", "ymax"))
                    boxes.append(((x0 + x1) / 2 / w, (y0 + y1) / 2 / h, (x1 - x0) / w, (y1 - y0) / h))
        if not boxes:
            dropped["no_boxes"] += 1
            continue
        clean = []
        for cx, cy, bw, bh in boxes:
            x0, y0 = max(0.0, cx - bw / 2), max(0.0, cy - bh / 2)
            x1, y1 = min(1.0, cx + bw / 2), min(1.0, cy + bh / 2)
            if x1 - x0 > 0.002 and y1 - y0 > 0.002:
                clean.append(((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0))
        if not clean:
            dropped["degenerate_boxes"] += 1
            continue
        if max(w * h for _, _, w, h in clean) > CROP_LIKE_AREA:
            dropped["crop_like"] += 1
            continue
        records.append({"source": name, "image": image, "boxes": clean, "key": (name, source_stem(image))})
    return records, dropped


def cmd_detector(args: argparse.Namespace) -> None:
    records, dropped = [], {}
    for name, (_, rel) in DETECTOR_SOURCES.items():
        recs, drop = detector_records(name, ROOT / rel)
        records += recs
        dropped[name] = dict(drop)
        print(f"{name:20s} kept {len(recs):5d}  dropped {dict(drop)}")

    uf = UnionFind()
    for rec in records:
        uf.find(rec["key"])
    merge_near_duplicates(uf, [(rec["key"], image_hash(rec["image"])) for rec in records], DETECTOR_NEAR_DUP_BITS)
    group_of = lambda rec: uf.find(rec["key"])  # noqa: E731
    forced = {group_of(r): "train" for r in records if r["source"] in TRAIN_ONLY_SOURCES}
    split = grouped_split(records, group_of, (0.8, 0.1), args.seed, forced)

    out = args.output
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; choose a new version directory")
    counts = defaultdict(Counter)
    rewritten = 0
    for i, rec in enumerate(records):
        s = split[group_of(rec)]
        stem = f"{rec['source']}__{i:05d}"
        rewritten += link(rec["image"], out / "images" / s / f"{stem}{rec['image'].suffix.lower()}")
        label = out / "labels" / s / f"{stem}.txt"
        label.parent.mkdir(parents=True, exist_ok=True)
        label.write_text("".join(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for cx, cy, w, h in rec["boxes"]))
        counts[s][rec["source"]] += 1
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: license_plate\n"
    )
    manifest = {
        "seed": args.seed,
        "group_key": f"roboflow source stem + dHash of the upright image within {DETECTOR_NEAR_DUP_BITS} bits, union-find",
        "train_only_sources": sorted(TRAIN_ONLY_SOURCES),
        "crop_like_area_threshold": CROP_LIKE_AREA,
        "exif_rotated_images_written_upright": rewritten,
        "sources": {k: {"licence": v[0], "path": str(ROOT / v[1])} for k, v in DETECTOR_SOURCES.items()},
        "dropped": dropped,
        "images_per_split": {s: sum(c.values()) for s, c in counts.items()},
        "boxes_per_split": {s: sum(len(r["boxes"]) for r in records if split[group_of(r)] == s) for s in counts},
        "per_source": {s: dict(c) for s, c in counts.items()},
        "groups": len({group_of(r) for r in records}),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: manifest[k] for k in ("images_per_split", "boxes_per_split", "groups")}, indent=2))


# ---------------------------------------------------------------- OCR


def ocr_records() -> list[dict]:
    records = []
    root = ROOT / OCR_SOURCES["kg-avinash-6"][1] / "license_plate_dataset"
    with (root / "annotations.csv").open(newline="") as fh:
        for row in csv.DictReader(fh):
            records.append({"source": "kg-avinash-6", "image": root / row["image_path"], "raw": row["plate_text"]})
    root = ROOT / OCR_SOURCES["kg-kp00011"][1]
    for labels in sorted(root.glob("*_labels.txt")):
        split_dir = root / "images" / labels.stem.removesuffix("_labels")
        for line in labels.read_text(errors="replace").splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2:
                records.append({"source": "kg-kp00011", "image": split_dir / parts[0], "raw": parts[1]})
    return records


def cmd_ocr(args: argparse.Namespace) -> None:
    records, dropped = [], Counter()
    for rec in ocr_records():
        text = norm_plate(rec["raw"])
        if not rec["image"].is_file():
            dropped["missing_image"] += 1
        elif not OCR_TEXT.match(text):
            dropped["text_not_4_to_11_alnum"] += 1
        else:
            records.append({**rec, "text": text})

    # Group by plate text, and merge texts whose crops are near-identical: frames of one plate whose labels
    # differ by a typo (GJO1HW3542 / GJ01HW3542) must not straddle splits.
    uf = UnionFind()
    for rec in records:
        uf.find(rec["text"])
    merge_near_duplicates(uf, [(rec["text"], image_hash(rec["image"])) for rec in records], OCR_NEAR_DUP_BITS)
    group_of = lambda rec: uf.find(rec["text"])  # noqa: E731
    split = grouped_split(records, group_of, (0.7, 0.15), args.seed)

    out = args.output
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; choose a new version directory")
    out.mkdir(parents=True)
    rows = defaultdict(list)
    for rec in records:
        rows[split[group_of(rec)]].append(rec)
    for s, recs in rows.items():
        with (out / f"{s}.csv").open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["image_path", "plate_text", "source"])
            for rec in sorted(recs, key=lambda r: str(r["image"])):
                writer.writerow([os.path.relpath(rec["image"].resolve(), out), rec["text"], rec["source"]])
    manifest = {
        "seed": args.seed,
        "group_key": f"plate_text, merged across crops within {OCR_NEAR_DUP_BITS} bits of dHash",
        "ratios": [0.7, 0.15, 0.15],
        "sources": {k: {"licence": v[0], "path": str(ROOT / v[1])} for k, v in OCR_SOURCES.items()},
        "dropped": dict(dropped),
        "images_per_split": {s: len(r) for s, r in rows.items()},
        "unique_texts_per_split": {s: len({r["text"] for r in recs}) for s, recs in rows.items()},
        "per_source": {s: dict(Counter(r["source"] for r in recs)) for s, recs in rows.items()},
        "max_text_len": max(len(r["text"]) for r in records),
        "text_overlap_train_test": len({r["text"] for r in rows["train"]} & {r["text"] for r in rows["test"]}),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("detector", cmd_detector), ("ocr", cmd_ocr)):
        p = sub.add_parser(name)
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--seed", type=int, default=42)
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
