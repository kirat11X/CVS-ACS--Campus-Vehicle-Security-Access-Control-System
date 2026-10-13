"""Audit 2026-10-13: the Track A detector split must keep every copy of one photo in one group.

The prepared plate_det_in_v1 split had 4 test images identical (after EXIF transpose) to train images
and 21 of 118 within 1 bit of dHash: the splitter hashed EXIF-rotated photos in their raw orientation
and merged only exact dHash matches, so Roboflow re-exports and re-encodes of a photo straddled splits.
"""
import random
import sys
from argparse import Namespace
from pathlib import Path

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

TRACK_A = Path(__file__).resolve().parents[2] / "finetune" / "track_a"
sys.path.insert(0, str(TRACK_A))
import prepare_plate_training_sets as prep  # noqa: E402

EXIF_ORIENTATION = 274
LABEL = "0 0.500000 0.620000 0.200000 0.080000\n"


def scene(seed: int) -> Image.Image:
    """A street-like 640x480 frame: random blocks plus a plate-sized white box."""
    rng = random.Random(seed)
    img = Image.new("RGB", (640, 480), tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(img)
    for _ in range(14):
        x0, y0 = rng.randrange(600), rng.randrange(440)
        draw.rectangle([x0, y0, x0 + rng.randrange(40, 320), y0 + rng.randrange(40, 240)],
                       fill=tuple(rng.randrange(256) for _ in range(3)))
    draw.rectangle([256, 278, 384, 316], fill=(250, 250, 250))
    return img


def save(img: Image.Image, image_path: Path, label_path: Path, exif_orientation=None, quality=95) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    if exif_orientation:
        exif = Image.Exif()
        exif[EXIF_ORIENTATION] = exif_orientation
        img.save(image_path, quality=quality, exif=exif)
    else:
        img.save(image_path, quality=quality)
    label_path.write_text(LABEL)


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    root = tmp_path / "datasets"
    upright = scene(1)
    # Kaggle original: pixels stored sideways with EXIF orientation 6 (viewers show it upright).
    save(upright.rotate(90, expand=True), root / "kg-x/images/photo.jpg", root / "kg-x/labels/photo.txt", exif_orientation=6)
    # Roboflow re-export of the same photo: auto-oriented, resized and re-encoded.
    save(upright.resize((576, 432)), root / "rf-y/train/images/photo_jpg.rf.0a1b.jpg",
         root / "rf-y/train/labels/photo_jpg.rf.0a1b.txt", quality=80)
    # Another dataset's copy: slightly softened.
    save(upright.filter(ImageFilter.GaussianBlur(1)), root / "kg-z/images/frame_0001.jpg",
         root / "kg-z/labels/frame_0001.txt", quality=90)
    for source in ("kg-x", "kg-z"):
        for seed in range(10):
            save(scene(100 + seed + (50 if source == "kg-z" else 0)),
                 root / f"{source}/images/other_{seed}.jpg", root / f"{source}/labels/other_{seed}.txt")
    monkeypatch.setattr(prep, "ROOT", root)
    monkeypatch.setattr(prep, "DETECTOR_SOURCES", {s: ("CC0-1.0", s) for s in ("kg-x", "rf-y", "kg-z")})
    monkeypatch.setattr(prep, "TRAIN_ONLY_SOURCES", set())
    return tmp_path


def test_copies_of_one_photo_share_a_group(dataset, monkeypatch):
    seen = {}
    real_split = prep.grouped_split

    def spy(items, group_of, ratios, seed, forced=None):
        seen["groups"] = {(item["source"], item["image"].name): group_of(item) for item in items}
        return real_split(items, group_of, ratios, seed, forced)

    monkeypatch.setattr(prep, "grouped_split", spy)
    prep.cmd_detector(Namespace(output=dataset / "out", seed=42))

    groups = seen["groups"]
    twins = {groups[("kg-x", "photo.jpg")], groups[("rf-y", "photo_jpg.rf.0a1b.jpg")], groups[("kg-z", "frame_0001.jpg")]}
    assert len(twins) == 1, f"copies of one photo landed in {len(twins)} groups: {twins}"
    distractors = {g for (_, name), g in groups.items() if name.startswith("other_")}
    assert len(distractors) == 20 and not (distractors & twins), "unrelated scenes must stay separate"
