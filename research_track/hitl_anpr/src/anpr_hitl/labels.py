"""Box geometry: YOLO-normalised <-> pixel, clipping, resize and letterbox mapping, label files."""

from __future__ import annotations

from pathlib import Path

from anpr_hitl.store import atomic_write_text

MIN_SIDE_PX = 2.0  # boxes thinner than this after clipping are dropped as degenerate


def yolo_to_xyxy(cx: float, cy: float, w: float, h: float, img_w: int, img_h: int) -> tuple[float, float, float, float]:
    return ((cx - w / 2) * img_w, (cy - h / 2) * img_h, (cx + w / 2) * img_w, (cy + h / 2) * img_h)


def clip_xyxy(box, img_w: int, img_h: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    x1, x2 = sorted((min(max(x1, 0.0), img_w), min(max(x2, 0.0), img_w)))
    y1, y2 = sorted((min(max(y1, 0.0), img_h), min(max(y2, 0.0), img_h)))
    return (x1, y1, x2, y2)


def xyxy_to_yolo(box, img_w: int, img_h: int) -> tuple[float, float, float, float] | None:
    """Clip to the image, then normalise; None for a degenerate box."""
    x1, y1, x2, y2 = clip_xyxy(box, img_w, img_h)
    if x2 - x1 < MIN_SIDE_PX or y2 - y1 < MIN_SIDE_PX:
        return None
    return ((x1 + x2) / 2 / img_w, (y1 + y2) / 2 / img_h, (x2 - x1) / img_w, (y2 - y1) / img_h)


def scale_xyxy(box, sx: float, sy: float) -> tuple[float, float, float, float]:
    """Map a box through a plain resize (sx = new_w / old_w, sy = new_h / old_h)."""
    x1, y1, x2, y2 = box
    return (x1 * sx, y1 * sy, x2 * sx, y2 * sy)


def letterbox_params(img_w: int, img_h: int, imgsz: int) -> tuple[float, float, float]:
    """Scale and padding Ultralytics uses to fit an image into imgsz x imgsz (centred padding)."""
    r = min(imgsz / img_w, imgsz / img_h)
    new_w, new_h = round(img_w * r), round(img_h * r)
    return r, (imgsz - new_w) / 2, (imgsz - new_h) / 2


def xyxy_to_letterbox(box, img_w: int, img_h: int, imgsz: int):
    r, pw, ph = letterbox_params(img_w, img_h, imgsz)
    x1, y1, x2, y2 = box
    return (x1 * r + pw, y1 * r + ph, x2 * r + pw, y2 * r + ph)


def xyxy_from_letterbox(box, img_w: int, img_h: int, imgsz: int):
    r, pw, ph = letterbox_params(img_w, img_h, imgsz)
    x1, y1, x2, y2 = box
    return clip_xyxy(((x1 - pw) / r, (y1 - ph) / r, (x2 - pw) / r, (y2 - ph) / r), img_w, img_h)


def iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def read_yolo_labels(path: Path, num_classes: int = 1) -> list[tuple[int, float, float, float, float]]:
    """Read a YOLO label file. An empty file means "no objects" (a valid negative); a missing file is an error."""
    labels = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            raise ValueError(f"{path}:{n}: expected 'class cx cy w h', got {line!r}")
        cls = int(parts[0])
        if not 0 <= cls < num_classes:
            raise ValueError(f"{path}:{n}: class id {cls} outside 0..{num_classes - 1}")
        cx, cy, w, h = (float(v) for v in parts[1:])
        if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < w <= 1 and 0 < h <= 1):
            raise ValueError(f"{path}:{n}: values outside [0, 1]: {line!r}")
        labels.append((cls, cx, cy, w, h))
    return labels


def write_yolo_labels(path: Path, labels) -> None:
    """Write (class, cx, cy, w, h) rows; an empty list writes an empty file (a negative image)."""
    atomic_write_text(Path(path), "".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h in labels))
