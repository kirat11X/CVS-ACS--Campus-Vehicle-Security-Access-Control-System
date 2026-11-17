import cv2
import numpy as np
import pytest

from anpr_hitl.config import load_config
from anpr_hitl.store import Store


@pytest.fixture
def cfg(tmp_path):
    return load_config(data_root=str(tmp_path / "data"))


@pytest.fixture
def store(cfg):
    return Store(cfg.data_root)


def make_video(path, fps=25, seconds=4, size=(640, 360), static_from=None, blur_frames=(), seed=0):
    """Synthetic H.264-ish test video: a moving block with the frame number printed on it.

    Frames >= static_from repeat one image (near-duplicates); frames in blur_frames are heavily blurred.
    """
    rng = np.random.default_rng(seed)
    background = np.full((size[1], size[0], 3), 110, dtype=np.uint8)
    for _ in range(40):  # sharp-edged clutter, so un-blurred frames are clearly sharp
        x, y = int(rng.integers(0, size[0] - 20)), int(rng.integers(0, size[1] - 20))
        colour = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(background, (x, y), (x + int(rng.integers(8, 60)), y + int(rng.integers(8, 60))), colour, -1)
    writer =cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    frozen = None
    for i in range(int(fps * seconds)):
        if static_from is not None and i >= static_from:
            frame = frozen.copy() if frozen is not None else background.copy()
        else:
            frame = background.copy()
            x = 20 + (i * 7) % (size[0] - 140)
            cv2.rectangle(frame, (x, 120), (x + 120, 220), (255, 255, 255), -1)
            cv2.putText(frame, f"{i:04d}", (x + 10, 185), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
        if static_from is not None and i == static_from - 1:
            frozen = frame.copy()
        if i in blur_frames:
            frame = cv2.GaussianBlur(frame, (0, 0), 12)
        writer.write(frame)
    writer.release()
    return path


def make_still(path, boxes, size=(640, 360), seed=0, text="PB65AB1234"):
    """A synthetic frame: dark clutter plus white 'plates' (with black text) at the given xyxy boxes."""
    rng = np.random.default_rng(seed)
    img = np.full((size[1], size[0], 3), 90, dtype=np.uint8)
    for _ in range(30):
        x, y = int(rng.integers(0, size[0] - 30)), int(rng.integers(0, size[1] - 30))
        colour = tuple(int(c) for c in rng.integers(0, 200, 3))  # never near-white
        cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 50)), y + int(rng.integers(8, 50))), colour, -1)
    for x1, y1, x2, y2 in boxes:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 255, 255), -1)
        cv2.putText(img, text[:4], (int(x1) + 6, int((y1 + y2) / 2) + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def white_box_detector(conf=0.9):
    """Fake detector: bounding boxes of white regions. `conf` may be a function of (frame_no, box_index)."""
    calls = {"n": 0}

    def detect(frames):
        out = []
        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            rects = sorted(cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > 400)
            xyxy = np.array([[x, y, x + w, y + h] for x, y, w, h in rects], dtype=float).reshape(-1, 4)
            scores = [conf(calls["n"], i) if callable(conf) else conf for i in range(len(xyxy))]
            out.append((xyxy, np.array(scores, dtype=float)))
            calls["n"] += 1
        return out

    detect.calls = calls
    return detect


def fake_reader(text="PB65AB1234", conf=0.95, char_conf=None):
    from anpr_hitl.ocr import OcrRead

    def read(crop):
        confs = list(char_conf) if char_conf is not None else [conf] * len(text)
        return OcrRead(text, float(np.mean(confs)) if confs else 0.0, confs, "fake", "char", 1)

    return read
