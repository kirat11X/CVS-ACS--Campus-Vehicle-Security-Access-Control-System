"""Search, download and profile public licence-plate datasets from Roboflow Universe and Kaggle.

Credentials: Roboflow key in $ROBOFLOW_API_KEY or ~/.config/roboflow/api_key; Kaggle token in ~/.kaggle/.
Payloads land in ~/ml-assets/campus/datasets (outside the repo) and respect the 30 GiB campus cap.

    python -I fetch_plate_datasets.py search --out candidates/
    python -I fetch_plate_datasets.py fetch rf:ws/project[/ver] kg:owner/slug https://universe.roboflow.com/ws/project
    python -I fetch_plate_datasets.py explore ROBOFLOW-x/v3 KAGGLE-y ... --out _explore/
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ASSET_ROOT = Path.home() / "ml-assets" / "campus" / "datasets"
CAMPUS_ROOT = ASSET_ROOT.parent
CAP_BYTES = 32212254720  # cap_bytes in track_a_dataset_manifest.yaml
MIN_HEADROOM = 200 * 1024**2
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
INDIAN_PLATE = re.compile(r"^([A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}|\d{2}BH\d{4}[A-Z]{1,2})$")
YOLO_LINE = re.compile(r"^\d+(\s+-?[\d.]+(e-?\d+)?){4,}$")
CORNER_LINE = re.compile(r"^(0?\.\d+|[01](\.0+)?)(\s+(0?\.\d+|[01](\.0+)?)){3}$")
PLATE_TEXT = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9]{4,12}$")

SEARCH_QUERIES = [
    "indian number plate",
    "indian license plate",
    "indian licence plate characters",
    "number plate ocr",
    "license plate characters",
    "license plate recognition",
    "license plate",
    "anpr",
]


def campus_bytes() -> int:
    out = subprocess.run(["du", "-sb", str(CAMPUS_ROOT)], capture_output=True, text=True, check=True)
    return int(out.stdout.split()[0])


def roboflow_key() -> str:
    key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    key_file = Path.home() / ".config" / "roboflow" / "api_key"
    if not key and key_file.is_file():
        key = key_file.read_text().strip()
    if not key:
        raise SystemExit("no Roboflow key: set ROBOFLOW_API_KEY or write ~/.config/roboflow/api_key")
    return key


def tool(name: str) -> str:
    """Resolve a CLI installed next to the running interpreter (venv bin) before falling back to PATH."""
    local = Path(sys.executable).parent / name
    return str(local) if local.is_file() else name


def parse_source(spec: str) -> tuple[str, str, int | None]:
    m = re.match(r"^(?:https?://)?universe\.roboflow\.com/([^/]+)/([^/?#]+)(?:/dataset/(\d+))?", spec)
    if m:
        return "roboflow", f"{m[1]}/{m[2]}", int(m[3]) if m[3] else None
    m = re.match(r"^(?:https?://)?(?:www\.)?kaggle\.com/datasets/([^/]+)/([^/?#]+)", spec)
    if m:
        return "kaggle", f"{m[1]}/{m[2]}", None
    m = re.match(r"^(rf|kg):([\w.-]+/[\w.-]+?)(?:/(\d+))?$", spec)
    if m:
        return ("roboflow" if m[1] == "rf" else "kaggle"), m[2], int(m[3]) if m[3] else None
    raise SystemExit(f"unrecognised source: {spec}")


# ---------------------------------------------------------------- search


def cmd_search(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    queries = args.query or SEARCH_QUERIES
    if not args.skip_roboflow:
        env = {**os.environ, "ROBOFLOW_API_KEY": roboflow_key()}
        results = {}
        for query in queries:
            proc = subprocess.run(
                [tool("roboflow"), "--json", "universe", "search", query, "--type", "dataset", "--limit", str(args.limit)],
                capture_output=True, text=True, env=env, cwd=args.out,
            )
            results[query] = json.loads(proc.stdout) if proc.stdout.strip().startswith(("{", "[")) else {"error": proc.stdout + proc.stderr}
        (args.out / "roboflow_search.json").write_text(json.dumps(results, indent=2))
        print(f"roboflow: {len(queries)} queries -> {args.out / 'roboflow_search.json'}")
    if not args.skip_kaggle:
        rows = []
        for query in queries:
            for page in range(1, args.kaggle_pages + 1):
                proc = subprocess.run(
                    [tool("kaggle"), "datasets", "list", "-s", query, "--csv", "--sort-by", "votes", "-p", str(page)],
                    capture_output=True, text=True, cwd=args.out,
                )
                page_rows = list(csv.DictReader(io.StringIO(proc.stdout))) if proc.returncode == 0 else []
                if proc.returncode != 0:
                    print(f"kaggle '{query}' p{page}: {proc.stderr.strip()[:200]}")
                rows += [{"query": query, **row} for row in page_rows]
                if not page_rows:
                    break
        seen, unique = set(), []
        for row in rows:
            if row.get("ref") not in seen:
                seen.add(row.get("ref"))
                unique.append(row)
        (args.out / "kaggle_search.json").write_text(json.dumps(unique, indent=2))
        print(f"kaggle: {len(unique)} unique datasets -> {args.out / 'kaggle_search.json'}")


# ---------------------------------------------------------------- fetch


def fetch_roboflow(slug: str, version: int | None, key: str) -> Path:
    import requests
    from roboflow import Roboflow

    workspace, project = slug.split("/")
    response = requests.get(f"https://api.roboflow.com/{workspace}/{project}", params={"api_key": key}, timeout=60)
    response.raise_for_status()
    meta = json.loads(response.text.replace(key, "<redacted>"))
    versions = sorted(int(v["id"].rsplit("/", 1)[1]) for v in meta.get("versions") or [])
    if not versions:
        raise RuntimeError("project has no generated versions")
    version = version or versions[-1]
    dest = ASSET_ROOT / f"ROBOFLOW-{project}" / f"v{version}"
    if (dest / "data.yaml").is_file():
        print(f"  already present: {dest}")
        return dest
    Roboflow(api_key=key).workspace(workspace).project(project).version(version).download(
        "yolov11", location=str(dest), overwrite=True
    )
    (dest / "source_meta.json").write_text(json.dumps({"source": slug, "version": version, **meta}, indent=2))
    return dest


def fetch_kaggle(slug: str, budget: int) -> Path:
    owner, name = slug.split("/")
    dest = ASSET_ROOT / f"KAGGLE-{owner}-{name}"
    if dest.is_dir() and any(dest.iterdir()):
        print(f"  already present: {dest}")
        return dest
    listing = subprocess.run([tool("kaggle"), "datasets", "files", slug, "--csv"], capture_output=True, text=True)
    sizes = [row.get("totalBytes") or row.get("size") or "" for row in csv.DictReader(io.StringIO(listing.stdout))]
    known = sum(int(s) for s in sizes if s.isdigit())
    if known > budget:
        raise RuntimeError(f"needs ~{known / 1e9:.2f} GB but only {budget / 1e9:.2f} GB left under the cap")
    dest.mkdir(parents=True)
    subprocess.run([tool("kaggle"), "datasets", "download", slug, "-p", str(dest), "--unzip"], check=True)
    subprocess.run([tool("kaggle"), "datasets", "metadata", slug, "-p", str(dest)], check=False)
    return dest


def cmd_fetch(args: argparse.Namespace) -> None:
    key = None
    done, failed = [], []
    for spec in args.sources:
        kind, slug, version = parse_source(spec)
        budget = CAP_BYTES - campus_bytes()
        if budget < MIN_HEADROOM:
            failed.append((spec, f"campus cap reached ({budget / 1e9:.2f} GB left)"))
            continue
        print(f"[{kind}] {slug}{f' v{version}' if version else ''}  ({budget / 1e9:.2f} GB left under cap)")
        try:
            if kind == "roboflow":
                key = key or roboflow_key()
                dest = fetch_roboflow(slug, version, key)
            else:
                dest = fetch_kaggle(slug, budget)
            done.append((spec, str(dest)))
        except Exception as exc:  # keep going: one bad project must not stop the batch
            failed.append((spec, f"{type(exc).__name__}: {exc}"))
            print(f"  FAILED: {exc}")
    print("\nfetched:")
    for spec, dest in done:
        print(f"  {spec} -> {dest}")
    if failed:
        print("failed/skipped:")
        for spec, reason in failed:
            print(f"  {spec}: {reason}")


# ---------------------------------------------------------------- explore


def read_names(root: Path) -> list[str]:
    import yaml

    for data_yaml in sorted(root.rglob("data.yaml")) + sorted(root.rglob("*.yaml")):
        try:
            data = yaml.safe_load(data_yaml.read_text())
        except Exception:
            continue
        names = data.get("names") if isinstance(data, dict) else None
        if isinstance(names, dict):
            return [str(names[k]) for k in sorted(names)]
        if isinstance(names, list):
            return [str(n) for n in names]
    for classes_txt in root.rglob("classes.txt"):
        return [line.strip() for line in classes_txt.read_text().splitlines() if line.strip()]
    return []


def parse_yolo(path: Path) -> list[tuple[int, float, float, float, float]] | None:
    boxes = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if CORNER_LINE.match(line):  # "x1 y1 x2 y2" normalised corners, no class id
            x0, y0, x1, y1 = (float(p) for p in line.split())
            boxes.append((0, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0))
            continue
        if not YOLO_LINE.match(line):
            return None
        parts = line.split()
        nums = [float(p) for p in parts[1:]]
        if len(nums) == 4:
            boxes.append((int(parts[0]), *nums))
        else:  # polygon -> bbox
            xs, ys = nums[0::2], nums[1::2]
            boxes.append((int(parts[0]), (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)))
    return boxes


def chars_to_text(boxes: list[tuple[int, float, float, float, float]], names: list[str]) -> str:
    """Read a plate string from character boxes: cluster into rows by y, then left-to-right."""
    boxes = sorted(boxes, key=lambda b: b[2])
    median_h = sorted(b[4] for b in boxes)[len(boxes) // 2]
    rows: list[list] = [[boxes[0]]]
    for box in boxes[1:]:
        if box[2] - rows[-1][-1][2] > 0.5 * median_h:
            rows.append([])
        rows[-1].append(box)
    return "".join(names[b[0]].upper() for row in rows for b in sorted(row, key=lambda b: b[1]))


def norm_plate(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def dhash(img) -> int:
    px = img.convert("L").resize((9, 8)).tobytes()
    return sum(1 << i for i in range(64) if px[(i // 8) * 9 + i % 8] < px[(i // 8) * 9 + i % 8 + 1])


def label_for(image: Path) -> Path:
    """YOLO label for an image: the parallel labels/ tree first, else a .txt beside the image."""
    parts = list(image.parts)
    for i in range(len(parts) - 2, -1, -1):
        if parts[i].lower() in {"images", "image", "imgs", "img"}:
            parts[i] = "labels"
            parallel = Path(*parts).with_suffix(".txt")
            if parallel.is_file():
                return parallel
            break
    return image.with_suffix(".txt")


def read_text_labels(files: list[Path], images: list[Path]) -> dict[Path, str]:
    """OCR labels from `image<TAB|,>text` files (TSV/CSV/TXT): image path -> normalised plate text.

    Label files often name images by bare filename and reuse names across splits, so each name is resolved
    against the real images, preferring the split named in the label file (train_labels.txt -> train/).
    """
    by_stem: dict[str, list[Path]] = {}
    for image in images:
        by_stem.setdefault(image.stem, []).append(image)
    labels: dict[Path, str] = {}
    for path in files:
        if path.suffix.lower() not in {".txt", ".tsv", ".csv"} or path.stat().st_size > 50 * 1024**2:
            continue
        lines = path.read_text(errors="replace").splitlines()
        if len(lines) < 20:
            continue
        split = next((s for s in ("train", "valid", "val", "test") if s in path.stem.lower()), None)
        found = {}
        for line in lines:
            fields = re.split(r"\t|,", line.strip())
            if len(fields) < 2:
                continue
            image = next((f for f in fields if Path(f.strip()).suffix.lower() in IMAGE_EXTS), None)
            text = next((norm_plate(f) for f in fields if f is not image and PLATE_TEXT.match(norm_plate(f))), None)
            if image and text:
                candidates = by_stem.get(Path(image.strip()).stem, [])
                if len(candidates) > 1 and split:
                    candidates = [c for c in candidates if split in c.parts] or candidates
                found[candidates[0] if candidates else path.parent / image.strip()] = text
        if len(found) >= 0.5 * len(lines):
            labels.update(found)
    return labels


def contact_sheet(images: list[Path], names: list[str], voc: dict[str, Path], ocr: dict[Path, str], out: Path) -> None:
    from PIL import Image, ImageDraw

    tile, cols = 320, 4
    picks = images[:16]
    sheet = Image.new("RGB", (tile * cols, tile * ((len(picks) + cols - 1) // cols)), "black")
    for i, path in enumerate(picks):
        try:
            with Image.open(path) as src:
                img = src.convert("RGB")
        except Exception:
            continue
        w, h = img.size
        draw = ImageDraw.Draw(img)
        label = label_for(path)
        boxes = parse_yolo(label) if label.is_file() else None
        for cls, cx, cy, bw, bh in boxes or []:
            draw.rectangle([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h], outline="lime", width=max(2, w // 200))
            draw.text(((cx - bw / 2) * w, max(0, (cy - bh / 2) * h - 12)), names[cls] if cls < len(names) else str(cls), fill="yellow")
        if path.stem in voc:
            for obj in ET.parse(voc[path.stem]).getroot().iter("object"):
                bb = obj.find("bndbox")
                if bb is not None:
                    x0, y0, x1, y1 = (float(bb.findtext(k, "0")) for k in ("xmin", "ymin", "xmax", "ymax"))
                    draw.rectangle([x0, y0, x1, y1], outline="lime", width=max(2, w // 200))
                    draw.text((x0, max(0, y0 - 12)), obj.findtext("name", ""), fill="yellow")
        img.thumbnail((tile, tile))
        sheet.paste(img, ((i % cols) * tile, (i // cols) * tile))
        caption = ocr.get(path) or (path.parent.name if not boxes and path.stem not in voc else "")
        if caption:
            draw_sheet = ImageDraw.Draw(sheet)
            x, y = (i % cols) * tile, (i // cols) * tile + tile - 16
            draw_sheet.rectangle([x, y, x + 8 * len(caption) + 6, y + 16], fill="black")
            draw_sheet.text((x + 3, y + 2), caption, fill="cyan")
    sheet.save(out, quality=85)


def profile(root: Path, out_dir: Path, seed: int) -> tuple[dict, set[int]]:
    from PIL import Image

    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    images = sorted(p for p in files if p.suffix.lower() in IMAGE_EXTS)
    ext_counts = Counter(p.suffix.lower() or "<none>" for p in files)
    names = read_names(root)
    report: dict = {
        "path": str(root),
        "bytes": sum(p.stat().st_size for p in files),
        "files_by_ext": dict(ext_counts.most_common(12)),
        "images": len(images),
        "splits": dict(Counter(next((s for s in ("train", "valid", "val", "test") if s in p.parts), "-") for p in images)),
        "class_names": names,
    }
    meta_files = [root / "source_meta.json", *root.glob("dataset-metadata.json")]
    for meta_file in meta_files:
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text())
            project = meta.get("project") or {}
            info = meta.get("info") or meta  # Kaggle nests the card under "info"
            report["license"] = project.get("license") or (info.get("licenses") or [{}])[0].get("name")
            report["title"] = project.get("name") or info.get("title")
            if meta.get("versions"):
                report["versions"] = {v["id"].rsplit("/", 1)[1]: v.get("images") for v in meta["versions"]}

    # YOLO labels
    class_hist, boxes_per_image, unlabelled, empty = Counter(), [], 0, 0
    yolo_files = 0
    char_ids = {i for i, n in enumerate(names) if n.strip().upper() in CHARS and len(n.strip()) == 1}
    plate_texts = []
    for image in images:
        label = label_for(image)
        if not label.is_file():
            unlabelled += 1
            continue
        boxes = parse_yolo(label)
        if boxes is None:
            continue
        yolo_files += 1
        if not boxes:
            empty += 1
        boxes_per_image.append(len(boxes))
        class_hist.update(b[0] for b in boxes)
        if len(char_ids) >= 20 and 4 <= len(boxes) <= 12 and all(b[0] in char_ids for b in boxes):
            plate_texts.append(chars_to_text(boxes, names))
    if yolo_files:
        report["yolo"] = {
            "labelled_images": yolo_files,
            "images_without_label_file": unlabelled,
            "empty_label_files": empty,
            "boxes": sum(boxes_per_image),
            "max_boxes_per_image": max(boxes_per_image),
            "class_hist": {names[k] if k < len(names) else str(k): v for k, v in class_hist.most_common()},
        }
    if len(char_ids) >= 20:
        indian = sum(bool(INDIAN_PLATE.match(t)) for t in plate_texts)
        report["character_level"] = {
            "char_classes": len(char_ids),
            "single_plate_images_read": len(plate_texts),
            "indian_format_match": indian,
            "indian_format_rate": round(indian / len(plate_texts), 3) if plate_texts else None,
            "samples": plate_texts[:15],
        }

    # VOC XML / COCO JSON / CSV
    voc = {p.stem: p for p in files if p.suffix.lower() == ".xml" and b"<annotation" in p.read_bytes()[:500]}
    if voc:
        obj_names = Counter()
        for xml in list(voc.values())[:5000]:
            try:
                obj_names.update(o.findtext("name", "").strip() for o in ET.parse(xml).getroot().iter("object"))
            except ET.ParseError:
                pass
        texty = [n for n in obj_names if INDIAN_PLATE.match(norm_plate(n))]
        report["voc"] = {"xml_files": len(voc), "object_names_top": dict(obj_names.most_common(15)), "names_like_indian_plate_text": len(texty)}
    coco = []
    for js in (p for p in files if p.suffix.lower() == ".json" and p.stat().st_size < 200 * 1024**2):
        try:
            data = json.loads(js.read_text())
        except Exception:
            continue
        if isinstance(data, dict) and "annotations" in data and "categories" in data:
            coco.append({"file": str(js.relative_to(root)), "images": len(data.get("images", [])), "annotations": len(data["annotations"]), "categories": [c.get("name") for c in data["categories"]][:40]})
    if coco:
        report["coco"] = coco
    tables = []
    for table in (p for p in files if p.suffix.lower() == ".csv"):
        with table.open(newline="", errors="replace") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            continue
        plate_cols = [h for i, h in enumerate(rows[0]) if sum(bool(INDIAN_PLATE.match(norm_plate(r[i]))) for r in rows[1:200] if i < len(r)) > 20]
        tables.append({"file": str(table.relative_to(root)), "rows": len(rows) - 1, "header": rows[0][:12], "first_row": rows[1][:12] if len(rows) > 1 else [], "columns_with_indian_plate_text": plate_cols})
    if tables:
        report["csv"] = tables

    # OCR text labels and folder-named classes
    ocr = read_text_labels(files, images)
    source = "label_file"
    if not ocr and not report.get("yolo") and not voc:
        # Some sets encode the plate in the filename ("KA 01 DX 5375.png", "ES465EA (2).jpg"). Plates alternate
        # letter/digit runs at least three times, which rejects "plate100", "Cars0" and "licensed_car12".
        from_names = {p: norm_plate(re.sub(r"(\s*\(\d+\)|_\d+)$", "", p.stem)) for p in images}
        from_names = {
            p: t for p, t in from_names.items()
            if PLATE_TEXT.match(t) and (INDIAN_PLATE.match(t) or len(re.findall(r"[A-Z]+|\d+", t)) >= 3)
        }
        if len(from_names) >= 0.3 * len(images) and len(set(from_names.values())) >= 0.5 * len(from_names):
            ocr, source = from_names, "filename"
    if ocr:
        texts = list(ocr.values())
        indian = sum(bool(INDIAN_PLATE.match(t)) for t in texts)
        report["ocr_text"] = {
            "source": source,
            "labelled_images": len(ocr),
            "matched_to_image_files": len(set(images) & ocr.keys()),
            "unique_texts": len(set(texts)),
            "indian_format_rate": round(indian / len(texts), 3),
            "state_codes_top": dict(Counter(t[:2] for t in texts if INDIAN_PLATE.match(t)).most_common(12)),
            "samples": texts[:12],
        }
    parents = Counter(p.parent.name for p in images)
    if not report.get("yolo") and not voc and not ocr and 10 <= len(parents) <= 100:
        report["folder_classes"] = dict(sorted(parents.items()))

    # integrity, sizes, hashes
    bad, dims, hashes = [], [], set()
    for image in images:
        try:
            with Image.open(image) as img:
                img.verify()
            with Image.open(image) as img:
                dims.append(img.size)
                hashes.add(dhash(img))
        except Exception as exc:
            bad.append(f"{image.relative_to(root)}: {type(exc).__name__}")
    if dims:
        ws, hs = sorted(d[0] for d in dims), sorted(d[1] for d in dims)
        report["image_size"] = {"median_wh": [ws[len(ws) // 2], hs[len(hs) // 2]], "min_wh": [ws[0], hs[0]], "max_wh": [ws[-1], hs[-1]], "distinct_sizes": len(set(dims))}
    report["corrupt_images"] = {"count": len(bad), "examples": bad[:5]}
    report["unique_dhash"] = len(hashes)

    if images:
        sample = random.Random(seed).sample(images, min(16, len(images)))
        sheet = out_dir / f"{root.relative_to(ASSET_ROOT).as_posix().replace('/', '__')}.jpg"
        contact_sheet(sample, names, voc, ocr, sheet)
        report["contact_sheet"] = str(sheet)
    return report, hashes


def cmd_explore(args: argparse.Namespace) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    reports, hashes = {}, {}
    for name in args.datasets:
        root = (ASSET_ROOT / name).resolve()
        print(f"profiling {root}")
        reports[name], hashes[name] = profile(root, args.out, args.seed)
    overlap = {}
    keys = list(hashes)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shared = len(hashes[a] & hashes[b])
            if shared:
                overlap[f"{a} <-> {b}"] = {"shared_dhash": shared, "of_smaller": round(shared / max(1, min(len(hashes[a]), len(hashes[b]))), 3)}
    result = {"datasets": reports, "pairwise_exact_dhash_overlap": overlap}
    (args.out / "explore.json").write_text(json.dumps(result, indent=2))
    print(f"wrote {args.out / 'explore.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search Roboflow Universe and Kaggle")
    search.add_argument("--out", type=Path, required=True)
    search.add_argument("--query", action="append", help="override the default query list (repeatable)")
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--kaggle-pages", type=int, default=2)
    search.add_argument("--skip-roboflow", action="store_true")
    search.add_argument("--skip-kaggle", action="store_true")
    search.set_defaults(func=cmd_search)

    fetch = sub.add_parser("fetch", help="download datasets into the campus asset root")
    fetch.add_argument("sources", nargs="+", help="rf:ws/project[/ver], kg:owner/slug, or a Universe/Kaggle URL")
    fetch.set_defaults(func=cmd_fetch)

    explore = sub.add_parser("explore", help="profile downloaded datasets")
    explore.add_argument("datasets", nargs="+", help="paths relative to the campus dataset root")
    explore.add_argument("--out", type=Path, default=ASSET_ROOT / "_explore")
    explore.add_argument("--seed", type=int, default=42)
    explore.set_defaults(func=cmd_explore)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
