"""Build grouped Indian LPR crop manifests from authorized four-point annotations.

Expected input JSONL fields: image, corners ([[x,y], ...]), text, optional vehicle_id.
This script only prepares data. It never downloads data or trains a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any


def _grouped_split(rows: list[dict[str, Any]], seed: int) -> dict[str, str]:
    groups = sorted({str(row["text"]).strip().upper() for row in rows})
    random.Random(seed).shuffle(groups)
    n = len(groups)
    cut = max(1, int(n * 0.7))
    val_cut = max(cut + 1, int(n * 0.85)) if n > 2 else n
    split_by_text = {
        text: ("train" if index < cut else "validation" if index < val_cut else "test")
        for index, text in enumerate(groups)
    }
    return split_by_text


def _record_hash(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.annotations.read_text(encoding="utf-8").splitlines() if line.strip()]
    split_by_text = _grouped_split(rows, args.seed)
    output_rows = []
    for row in rows:
        corners = row.get("corners")
        if not isinstance(corners, list) or len(corners) != 4:
            raise ValueError("each annotation needs exactly four ordered corners")
        text = str(row.get("text") or "").strip().upper()
        if not text:
            raise ValueError("empty plate text is not a training label")
        output_rows.append({
            "image": str(row["image"]),
            "corners": corners,
            "text": text,
            "vehicle_id": row.get("vehicle_id"),
            "split": split_by_text[text],
            "source_record_sha256": _record_hash(row),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"seed": args.seed, "group_key": "plate_text", "records": output_rows}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
