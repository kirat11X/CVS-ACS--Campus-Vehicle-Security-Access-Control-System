"""Audit 2026-10-13: Track A OCR split must keep frames of one plate together even when a label has a typo.

prepared/ocr_in_v1 is grouped by plate text, merging texts only for pixel-identical crops. Consecutive
frames of one plate labelled GJO1HW3542 (letter O) in train and GJ01HW3542 in test, and GJ27TG0469 /
GJ27TG0466 across val and test, are within 1-2 bits of dHash but landed in different splits.
"""
import sys
from argparse import Namespace
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

TRACK_A = Path(__file__).resolve().parents[2] / "finetune" / "track_a"
sys.path.insert(0, str(TRACK_A))
import prepare_plate_training_sets as prep  # noqa: E402
from fetch_plate_datasets import dhash  # noqa: E402


def crop(text: str, background: int = 245, shift: int = 0) -> Image.Image:
    img = Image.new("RGB", (160, 50), (background,) * 3)
    draw = ImageDraw.Draw(img)
    draw.rectangle([1, 1, 158, 48], outline=(20, 20, 20), width=3)
    draw.text((14 + shift, 10), text, fill=(0, 0, 0), font_size=26)
    return img


def test_typo_labelled_frames_of_one_plate_share_a_group(tmp_path, monkeypatch):
    plate = crop("GJ01HW3542")
    next_frame = crop("GJ01HW3542", shift=1)  # the vehicle moved one pixel
    distractors = {"MH12AB1234": crop("MH12AB1234", 200, 6), "KA05MN7788": crop("KA05MN7788", 160, -4),
                   "DL3CAF0001": crop("DL3CAF0001", 120, 10), "TN09BX4421": crop("TN09BX4421", 225, -8)}
    assert 1 <= bin(dhash(plate) ^ dhash(next_frame)).count("1") <= 2, "fixture: frames must be near, not identical"

    records = []
    for name, img, label in [("frame_138.png", plate, "GJO1HW3542"), ("frame_139.png", next_frame, "GJ01HW3542"),
                             *[(f"{text}.png", img, text) for text, img in distractors.items()]]:
        img.save(tmp_path / name)
        records.append({"source": "kg-avinash-6", "image": tmp_path / name, "raw": label})
    monkeypatch.setattr(prep, "ocr_records", lambda: records)

    seen = {}
    real_split = prep.grouped_split

    def spy(items, group_of, ratios, seed, forced=None):
        seen.update({item["image"].name: group_of(item) for item in items})
        return real_split(items, group_of, ratios, seed, forced)

    monkeypatch.setattr(prep, "grouped_split", spy)
    prep.cmd_ocr(Namespace(output=tmp_path / "out", seed=42))

    assert seen["frame_138.png"] == seen["frame_139.png"], "frames of one plate split apart by a label typo"
    assert len({seen[f"{text}.png"] for text in distractors} | {seen["frame_138.png"]}) == 5, "distinct plates must stay separate"
