"""Normalize vehicle detection/classification annotations into a manifest.

This is intentionally separate from plate OCR. Accepted input is COCO JSON with
image-level vehicle annotations. It does not infer vehicle classes from plates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coco", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.coco.read_text(encoding="utf-8"))
    categories = {item["id"]: item["name"] for item in data.get("categories", [])}
    images = {item["id"]: item for item in data.get("images", [])}
    records = []
    for annotation in data.get("annotations", []):
        image = images.get(annotation.get("image_id"))
        category = categories.get(annotation.get("category_id"))
        if image is None or not category:
            continue
        records.append({
            "image": image["file_name"],
            "vehicle_class": category,
            "bbox_xywh": annotation.get("bbox"),
            "source_annotation_id": annotation.get("id"),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"task": "vehicle_classification", "records": records}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
