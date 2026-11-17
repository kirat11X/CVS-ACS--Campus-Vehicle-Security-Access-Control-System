import random

import pytest

from anpr_hitl.labels import (
    clip_xyxy,
    iou,
    letterbox_params,
    read_yolo_labels,
    scale_xyxy,
    write_yolo_labels,
    xyxy_from_letterbox,
    xyxy_to_letterbox,
    xyxy_to_yolo,
    yolo_to_xyxy,
)


@pytest.mark.parametrize("img_w, img_h", [(1920, 1080), (3840, 2160), (2160, 3840), (640, 480), (37, 23)])
def test_yolo_pixel_round_trip(img_w, img_h):
    rng = random.Random(img_w * img_h)
    for _ in range(500):
        x1, y1 = rng.uniform(0, img_w - 3), rng.uniform(0, img_h - 3)
        x2, y2 = rng.uniform(x1 + 2.5, img_w), rng.uniform(y1 + 2.5, img_h)
        yolo = xyxy_to_yolo((x1, y1, x2, y2), img_w, img_h)
        back = yolo_to_xyxy(*yolo, img_w, img_h)
        assert all(abs(a - b) < 1e-6 for a, b in zip((x1, y1, x2, y2), back))
        assert all(0 <= v <= 1 for v in yolo)


def test_clipping_and_degenerate_boxes():
    assert clip_xyxy((-10, -5, 50, 2000), 100, 100) == (0.0, 0.0, 50, 100)
    assert clip_xyxy((80, 70, 20, 10), 100, 100) == (20, 10, 80, 70)       # swapped corners are reordered
    assert xyxy_to_yolo((150, 10, 300, 40), 100, 100) is None              # fully outside -> degenerate
    assert xyxy_to_yolo((10, 10, 11, 50), 100, 100) is None                 # 1 px wide -> degenerate
    cx, cy, w, h = xyxy_to_yolo((-20, 10, 40, 30), 100, 100)               # partly outside -> clipped
    assert (round(cx, 3), round(w, 3)) == (0.2, 0.4)


@pytest.mark.parametrize("img_w, img_h, imgsz", [(1920, 1080, 1280), (2160, 3840, 1280), (1280, 720, 640), (640, 640, 640)])
def test_letterbox_round_trip(img_w, img_h, imgsz):
    r, pw, ph = letterbox_params(img_w, img_h, imgsz)
    assert min(pw, ph) <= 0.5 and r == pytest.approx(min(imgsz / img_w, imgsz / img_h))  # fills one side
    box =(img_w * 0.31, img_h * 0.62, img_w * 0.44, img_h * 0.69)
    lb = xyxy_to_letterbox(box, img_w, img_h, imgsz)
    assert all(0 <= v <= imgsz for v in lb)
    back = xyxy_from_letterbox(lb, img_w, img_h, imgsz)
    assert all(abs(a - b) < 1e-6 * max(img_w, img_h) for a, b in zip(box, back))


def test_resize_scaling_keeps_normalised_labels():
    box = (100, 200, 300, 260)
    resized = scale_xyxy(box, 0.5, 0.5)
    assert xyxy_to_yolo(box, 1920, 1080) == pytest.approx(xyxy_to_yolo(resized, 960, 540))


def test_label_files_round_trip_and_empty_negatives(tmp_path):
    path = tmp_path / "a.txt"
    rows = [(0, 0.5, 0.5, 0.1, 0.05), (0, 0.25, 0.75, 0.2, 0.04)]
    write_yolo_labels(path, rows)
    assert read_yolo_labels(path) == pytest.approx(rows)
    write_yolo_labels(path, [])
    assert path.read_text() == "" and read_yolo_labels(path) == []
    with pytest.raises(FileNotFoundError):
        read_yolo_labels(tmp_path / "missing.txt")


@pytest.mark.parametrize("line", ["1 0.5 0.5 0.1 0.1", "0 0.5 0.5 0.1", "0 1.5 0.5 0.1 0.1", "0 0.5 0.5 0 0.1"])
def test_bad_label_lines_are_rejected(tmp_path, line):
    path = tmp_path / "bad.txt"
    path.write_text(line + "\n")
    with pytest.raises(ValueError):
        read_yolo_labels(path, num_classes=1)


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
