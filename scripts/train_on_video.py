"""
Fine-tunes the plate detector on the boxes you corrected for one video (training/<video>/images/*.json).

    research_track/hitl_anpr/.venv/bin/python scripts/train_on_video.py 1
    research_track/hitl_anpr/.venv/bin/python scripts/train_on_video.py 1 --epochs 10

What it does, following the HITL pipeline's own round recipe (research_track/hitl_anpr/src/anpr_hitl/dataset.py):
  train = your corrected frames of this video (a frame with no box is a frame with no plate: you reviewed it)
        + replay of the original public training data (>= train.replay_fraction of the images), so the detector does
          not forget what it already knew
  val   = the public val set (never GOLD); the video you test on is never part of train or val
  start = the registry champion, fine-tuned with the small round learning rate, using the project's resume-safe,
          heat-guarded trainer. Re-running the same command resumes an interrupted run.
Boxes you unticked in AnyLabeling (scripts/anylabel.py saves them as "excluded": true) are NOT trained on: they are left
out of the labels and their pixels are blanked in the training copy of the frame, so a real plate you excluded is not
taught as "background" either. Your original frames are never changed.
Every image is checked against GOLD (identical bytes or near-duplicate) before anything is written.

NOTHING IS PROMOTED. The result is a candidate in <data_root>/runs/ft_video<N>/; the registry and the champion are
untouched, and GOLD is not evaluated. Plate TEXT is not trained: OCR fine-tuning waits for train.ocr_finetune_min_crops.
"""
import argparse
import hashlib
import json
import random
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "research_track" / "hitl_anpr" / "src"))
try:
    import cv2

    from anpr_hitl.config import load_config
    from anpr_hitl.dataset import LeakageError, _bootstrap_rows, gold_hashes, replay_count
    from anpr_hitl.hashing import image_dhash, sha256_file
    from anpr_hitl.labels import write_yolo_labels, xyxy_to_yolo
    from anpr_hitl.registry import Registry
    from anpr_hitl.splits import leakage_check
    from anpr_hitl.store import Store, atomic_write_json, atomic_write_text
    from anpr_hitl.train import preflight, train_detector
except ImportError as exc:
    sys.exit(f"{exc}\nRun this with the HITL environment: research_track/hitl_anpr/.venv/bin/python {sys.argv[0]} ...")


def labels_fingerprint(folder):
    """Hash of every label file: changes whenever you add, move, delete or exclude a box."""
    digest = hashlib.sha256()
    for jpath in sorted((folder / "images").glob("*.json")):
        digest.update(jpath.name.encode())
        digest.update(jpath.read_bytes())
    return digest.hexdigest()


def video_rows(folder, label):
    """One row per labelled frame: image, boxes to train on, and excluded boxes (xyxy, pixels) from the AnyLabeling JSONs."""
    rows, skipped = [], 0
    for jpath in sorted((folder / "images").glob("*.json")):
        data = json.loads(jpath.read_text())
        image = jpath.parent / data["imagePath"]
        w, h = data["imageWidth"], data["imageHeight"]
        boxes, excluded, ai_boxes = [], [], 0
        for s in data.get("shapes", []):
            if s.get("shape_type") != "rectangle" or s.get("label") != label or len(s["points"]) != 2:
                skipped += 1
                continue
            xs, ys = [p[0] for p in s["points"]], [p[1] for p in s["points"]]
            box = (max(min(xs), 0), max(min(ys), 0), min(max(xs), w), min(max(ys), h))
            (excluded if s.get("excluded") else boxes).append(box)
            ai_boxes += bool(s.get("reviewer")) and not s.get("excluded")
        rows.append({"key": jpath.stem, "image": image, "boxes": boxes, "excluded_boxes": excluded, "size": (w, h),
                     "ai_boxes": ai_boxes})
    return rows, skipped


def write_training_copy(row, dst):
    """Copy the frame; blank the pixels of excluded boxes, but never the pixels of a box that is kept."""
    if not row["excluded_boxes"]:
        shutil.copyfile(row["image"], dst)
        return
    img = cv2.imread(str(row["image"]))
    out = img.copy()

    def window(box):
        x1, y1, x2, y2 = box
        return slice(int(y1), int(y2) + 1), slice(int(x1), int(x2) + 1)

    for box in row["excluded_boxes"]:
        out[window(box)] = 114  # the grey Ultralytics pads images with
    for box in row["boxes"]:
        out[window(box)] = img[window(box)]
    cv2.imwrite(str(dst), out, [cv2.IMWRITE_JPEG_QUALITY, 95])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("videos", nargs="+", help="video number(s)/name(s), as given to extract_plates.py (e.g. 2 3 4)")
    parser.add_argument("--run", help="run name (default: ft_video<N> or ft_videos<first>-<last>)")
    parser.add_argument("--epochs-patience", type=int, help="early-stop patience in epochs (default: train.patience)")
    parser.add_argument("--dir", default=str(PROJECT_ROOT / "training"), help="parent folder holding <video>/ (default: training/)")
    parser.add_argument("--epochs", type=int, help="fine-tuning epochs (default: train.round_epochs in config.yaml)")
    parser.add_argument("--dataset-only", action="store_true", help="build and report the dataset, but do not train")
    parser.add_argument("--force", action="store_true", help="rebuild the dataset and start the run over")
    args = parser.parse_args()

    cfg = load_config()
    store = Store(cfg.data_root)
    folders = [Path(args.dir).expanduser().resolve() / v for v in args.videos]
    for folder in folders:
        if not (folder / "images").is_dir():
            sys.exit(f"{folder / 'images'} not found; run extract_plates.py {folder.name} first.")
    run_id = args.run or (f"ft_video{args.videos[0]}" if len(args.videos) == 1 else f"ft_videos{args.videos[0]}-{args.videos[-1]}")
    out, run_dir = store.dataset_dir(run_id), store.runs_dir(run_id)

    champion = Registry(store).champion()
    if champion is None:
        sys.exit("The registry has no champion model to fine-tune.")
    base = Path(champion["weights_path"])

    if args.force:
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(run_dir, ignore_errors=True)
    fingerprint = hashlib.sha256("".join(labels_fingerprint(f) for f in folders).encode()).hexdigest()
    if (out / "summary.json").is_file() and not args.force:
        built = json.loads((out / "summary.json").read_text()).get("labels_sha256")
        if built != fingerprint:
            sys.exit(f"Your boxes have changed since {out} was built (or it predates this check): run with --force to rebuild "
                     "the dataset from the current boxes and start the training over.")
    if not (out / "data.yaml").is_file():
        shutil.rmtree(out, ignore_errors=True)  # a half-built dataset from an interrupted attempt
        new, skipped = [], 0
        for folder in folders:
            rows, n_skipped = video_rows(folder, cfg.class_names[0])
            new += rows
            skipped += n_skipped
        n_boxes = sum(len(r["boxes"]) for r in new)
        ai_boxes = sum(r["ai_boxes"] for r in new)
        if n_boxes == 0:
            sys.exit("No plate boxes in the JSON files; nothing to train on.")
        old = _bootstrap_rows(store, "seed")
        n_replay = replay_count(len(new), len(old), cfg.train.replay_fraction)
        replay = sorted(random.Random(f"{cfg.seed}:{run_id}:replay").sample(sorted(old, key=lambda r: r["key"]), n_replay),
                        key=lambda r: r["key"])
        val = _bootstrap_rows(store, "val")
        train = new + replay

        gold_sha, gold_dh = gold_hashes(store)
        for row in train + val:
            row["sha256"] = sha256_file(row["image"])
            if row.get("dhash") is None:
                row["dhash"] = image_dhash(row["image"])
        leaks = [r["key"] for r in train + val if r["sha256"] in gold_sha]
        leaks += [f"{p}" for p in leakage_check({"train": [(r["key"], r["dhash"]) for r in train],
                                                "val": [(r["key"], r["dhash"]) for r in val], "gold": gold_dh},
                                               cfg.splits.leakage_max_bits)]
        if leaks:
            raise LeakageError(f"{len(leaks)} images leak into GOLD or between train and val, e.g. {leaks[:3]}")

        for split, rows in (("train", train), ("val", val)):
            img_dir, lbl_dir = out / split / "images", out / split / "labels"
            img_dir.mkdir(parents=True, exist_ok=True)
            lbl_dir.mkdir(parents=True, exist_ok=True)
            for i, row in enumerate(rows):
                stem = f"{i:05d}_{row['key'].replace('/', '__')}"
                dst = img_dir / f"{stem}{row['image'].suffix.lower()}"
                if "boxes" in row:  # your frames are copied (excluded boxes blanked); the public replay/val images are linked
                    write_training_copy(row, dst)
                    w, h = row["size"]
                    write_yolo_labels(lbl_dir / f"{stem}.txt", [(0, *y) for b in row["boxes"] if (y := xyxy_to_yolo(b, w, h))])
                else:
                    dst.symlink_to(row["image"].resolve())
                    shutil.copyfile(row["label_file"], lbl_dir / f"{stem}.txt")
        atomic_write_text(out / "data.yaml",
                          f"path: {out}\ntrain: train/images\nval: val/images\nnames:\n  0: {cfg.class_names[0]}\n")
        atomic_write_json(out / "summary.json", {
            "video_folders": [str(f) for f in folders], "ai_reviewed_boxes": ai_boxes, "video_frames": len(new), "video_frames_without_plates": sum(not r["boxes"] for r in new),
            "video_boxes": n_boxes, "excluded_boxes": sum(len(r["excluded_boxes"]) for r in new),
            "frames_with_excluded_boxes": sum(bool(r["excluded_boxes"]) for r in new), "ignored_shapes": skipped,
            "labels_sha256": fingerprint, "replay": len(replay), "replay_pool": len(old),
            "train_images": len(train), "val_images": len(val), "base_model": champion["version"],
            "base_weights_sha256": champion["weights_sha256"], "gold_leaks": 0,
            "note": "Candidate only: not registered, not promoted, GOLD not evaluated.",
        })
    summary = json.loads((out / "summary.json").read_text())
    print(f"dataset {out}: {summary['video_frames']} frames of video(s) {' '.join(args.videos)} ({summary['video_boxes']} boxes, "
          f"{summary['video_frames_without_plates']} frames without plates, {summary['excluded_boxes']} excluded boxes left out) "
          f"+ {summary['replay']} replay = "
          f"{summary['train_images']} train images; {summary['val_images']} val images")

    if args.epochs_patience:
        cfg.train.patience = args.epochs_patience
    if args.dataset_only:
        return
    problems = preflight()
    if problems:
        sys.exit("Not starting GPU training: " + "; ".join(problems))
    epochs = args.epochs or cfg.train.round_epochs
    print(f"fine-tuning {champion['version']} for up to {epochs} epochs -> {run_dir}", flush=True)
    result = train_detector(out / "data.yaml", base, run_dir, cfg, epochs=epochs, finetune=True)
    print(f"\ndone in {result.seconds:.0f}s{' (resumed)' if result.resumed else ''}"
          + (f"; stopped early: {result.stopped_reason}" if result.stopped_reason else ""))
    print(f"  best weights: {result.best}\n  last weights: {result.last}\n  final val metrics: {result.final_metrics}")
    print("Candidate only: the champion, the registry and GOLD are untouched.")


if __name__ == "__main__":
    main()
