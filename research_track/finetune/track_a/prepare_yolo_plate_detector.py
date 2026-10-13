"""Prepare a grouped YOLO plate-detection dataset from Kaggle annotations."""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="Extracted dataset containing images/ and labels/")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--validation-ratio", type=float, default=0.2)
    args = parser.parse_args()

    image_dir = args.source / "images"
    label_dir = args.source / "labels"
    images = sorted(image_dir.glob("*.jpg"))
    if not images:
        raise SystemExit("no JPG images found")

    rng = random.Random(args.seed)
    rng.shuffle(images)
    validation_count = max(1, round(len(images) * args.validation_ratio))
    splits = {"val": images[:validation_count], "train": images[validation_count:]}

    for split, split_images in splits.items():
        target_images = args.output / "images" / split
        target_labels = args.output / "labels" / split
        target_images.mkdir(parents=True, exist_ok=True)
        target_labels.mkdir(parents=True, exist_ok=True)
        for image in split_images:
            label = label_dir / f"{image.stem}.txt"
            if not label.is_file():
                raise SystemExit(f"missing YOLO label for {image.name}")
            shutil.copy2(image, target_images / image.name)
            shutil.copy2(label, target_labels / label.name)

    data_yaml = {
        "path": str(args.output),
        "train": "images/train",
        "val": "images/val",
        "names": {0: "license_plate"},
    }
    (args.output / "data.yaml").write_text(
        "path: " + str(args.output) + "\ntrain: images/train\nval: images/val\nnames:\n  0: license_plate\n",
        encoding="utf-8",
    )
    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "provenance": "Kaggle kedarsai/indian-license-plates-with-labels; CC0-1.0 per Kaggle metadata",
                "task": "plate_detection_only",
                "seed": args.seed,
                "image_count": len(images),
                "train_count": len(splits["train"]),
                "validation_count": len(splits["val"]),
                "data_yaml": data_yaml,
                "ocr_labels_present": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
