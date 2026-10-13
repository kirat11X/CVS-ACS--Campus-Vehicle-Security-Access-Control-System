"""Audit 2026-10-13: OCR labels that are not Indian plates must be flagged, never rewritten.

ocr_in_v1 accepts any 4-11 character alphanumeric label: 97 labels (12 in test) fail both the standard
and the BH-series pattern - e.g. BLUR, DUSTER, KL01KLKL01, GJO3PA4070 (letter O in the RTO digits) - and
nothing records them, so test accuracy is partly scored against gold labels no reader can produce.
"""
import csv
import sys
from argparse import Namespace
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

TRACK_A = Path(__file__).resolve().parents[2] / "finetune" / "track_a"
sys.path.insert(0, str(TRACK_A))
import prepare_plate_training_sets as prep  # noqa: E402


def test_non_indian_labels_are_flagged_and_kept_verbatim(tmp_path, monkeypatch):
    labels = ["GJO1HW3542", "BLUR", "MH12AB1234", "22BH1234AA", "DL3CAF0001"]
    records = []
    for i, text in enumerate(labels):
        path = tmp_path / f"crop_{i}.png"
        Image.new("RGB", (160, 50), (40 * i, 255 - 40 * i, 90)).save(path)
        records.append({"source": "kg-avinash-6", "image": path, "raw": text})
    monkeypatch.setattr(prep, "ocr_records", lambda: records)

    out = tmp_path / "out"
    prep.cmd_ocr(Namespace(output=out, seed=42))

    import json
    manifest = json.loads((out / "manifest.json").read_text())
    flagged = {t for texts in manifest.get("labels_not_indian_format", {}).values() for t in texts}
    assert flagged == {"GJO1HW3542", "BLUR"}, f"flagged labels: {sorted(flagged)}"
    written = {row["plate_text"] for split in ("train", "val", "test") if (out / f"{split}.csv").exists()
               for row in csv.DictReader((out / f"{split}.csv").open())}
    assert written == set(labels), "labels must be kept verbatim (flag, never rewrite or drop)"
