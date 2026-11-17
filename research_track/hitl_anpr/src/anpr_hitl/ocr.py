"""Plate readers behind one interface: RapidOCR (PP-OCRv4 English recogniser), Tesseract, fast-plate-ocr.

A reader returns the text exactly as recognised (normalised to A-Z0-9) with one confidence per kept character.
Nothing is corrected here: plates.check_plate flags formats and confusable characters for the reviewer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache

import cv2
import numpy as np

from anpr_hitl.config import OcrConfig
from anpr_hitl.plates import check_plate, normalize_plate

HSRP_EMBLEM = "IND"  # the "IND" mark on high-security plates is not part of the registration number
TESSERACT_CONFIG = "--psm 6 --oem 1 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
FAST_PLATE_MODEL = "cct-s-v2-global-model"


@dataclass
class OcrRead:
    text: str                                  # normalised, exactly as read (may be empty)
    conf: float                                # mean character confidence (0 for an empty read)
    char_confs: list[float] | None             # aligned with text; None when the engine gives none
    engine: str
    granularity: str = "char"                  # "char", or "word"/"line" when one score is shared by several chars
    lines: int = 0
    alternatives: list[dict] = field(default_factory=list)  # other engines' reads (never merged into text)

    @property
    def min_char_conf(self) -> float | None:
        return min(self.char_confs) if self.char_confs else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["conf"] = round(d["conf"], 4)
        d["char_confs"] = [round(c, 4) for c in self.char_confs] if self.char_confs is not None else None
        return d


def _join_lines(lines: list[tuple[float, float, float, str, list[float]]]) -> tuple[str, list[float]]:
    """lines: (y_centre, x_left, height, text, char_confs). Rows top to bottom, left to right within a row."""
    lines = [ln for ln in lines if ln[3] and ln[3] != HSRP_EMBLEM]
    lines.sort(key=lambda ln: ln[0])
    rows: list[list] = []
    for ln in lines:
        if rows and abs(ln[0] - rows[-1][0][0]) < 0.5 * max(ln[2], rows[-1][0][2]):
            rows[-1].append(ln)
        else:
            rows.append([ln])
    text, confs = "", []
    for row in rows:
        for ln in sorted(row, key=lambda item: item[1]):
            text += ln[3]
            confs += ln[4]
    return text, confs


def _read(text: str, confs: list[float], engine: str, granularity: str, lines: int) -> OcrRead:
    if len(confs) != len(text):  # defensive: never pretend a misaligned score belongs to a character
        return OcrRead(text, 0.0, None, engine, "none", lines)
    return OcrRead(text, float(np.mean(confs)) if confs else 0.0, confs if text else [], engine, granularity, lines)


class RapidOcrReader:
    name = "rapidocr"

    def __init__(self, version: str = "PP-OCRv4", lang: str = "en", model_type: str = "mobile", det_side: int = 160):
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        self.version = f"{version}-{lang}-{model_type}"
        self.engine = RapidOCR(params={
            "Rec.ocr_version": OCRVersion(version), "Rec.lang_type": LangRec(lang), "Rec.model_type": ModelType(model_type),
            "Det.limit_side_len": det_side, "Global.log_level": "error",
        })

    def read(self, crop_bgr: np.ndarray) -> OcrRead:
        res = self.engine(crop_bgr, return_word_box=True, return_single_char_box=True)
        if not res.txts:
            return OcrRead("", 0.0, [], f"{self.name}:{self.version}", "char", 0)
        words = res.word_results or [None] * len(res.txts)
        lines, granularity = [], "char"
        for box, txt, score, word in zip(res.boxes, res.txts, res.scores, words, strict=True):
            box = np.asarray(box, dtype=float)
            text = normalize_plate(txt)
            confs: list[float] = []
            for ch, ch_score, *_ in (word or ()):
                confs += [float(ch_score)] * len(normalize_plate(ch))
            if len(confs) != len(text):  # no usable per-character scores: share the line score
                confs, granularity = [float(score)] * len(text), "line"
            lines.append((box[:, 1].mean(), box[:, 0].min(), np.ptp(box[:, 1]), text, confs))
        text, confs = _join_lines(lines)
        return _read(text, confs, f"{self.name}:{self.version}", granularity, len(lines))


class TesseractReader:
    name = "tesseract"

    def read(self, crop_bgr: np.ndarray) -> OcrRead:
        import pytesseract

        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        if gray.shape[0] < 64:
            scale = 64 / gray.shape[0]
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        data = pytesseract.image_to_data(gray, config=TESSERACT_CONFIG, output_type=pytesseract.Output.DICT)
        by_line: dict[tuple, list] = {}
        for i, word in enumerate(data["text"]):
            text, conf = normalize_plate(word), float(data["conf"][i])
            if not text or conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            by_line.setdefault(key, []).append((data["left"][i], data["top"][i], data["height"][i], text, conf / 100))
        lines = []
        for words in by_line.values():
            words.sort()
            text = "".join(w[3] for w in words)
            confs = [w[4] for w in words for _ in w[3]]  # Tesseract scores words, not characters
            top = min(w[1] for w in words)
            height = max(w[2] for w in words)
            lines.append((top + height / 2, words[0][0], height, text, confs))
        text, confs = _join_lines(lines)
        return _read(text, confs, self.name, "word", len(lines))


class FastPlateReader:
    name = "fast_plate_ocr"

    def __init__(self, model: str = FAST_PLATE_MODEL):
        from fast_plate_ocr import LicensePlateRecognizer

        self.model_name = model
        self.model = LicensePlateRecognizer(model)

    def read(self, crop_bgr: np.ndarray) -> OcrRead:
        channels = self.model.config.image_color_mode
        img = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY if channels == "grayscale" else cv2.COLOR_BGR2RGB)
        pred = self.model.run_one(img, return_confidence=True)
        raw = pred.plate or ""
        probs = [float(p) for p in (pred.char_probs if pred.char_probs is not None else [])]
        text, confs = "", []
        for ch, p in zip(raw, probs, strict=False):  # probs may cover padding slots past the text
            norm = normalize_plate(ch)
            text += norm
            confs += [p] * len(norm)
        return _read(text, confs, f"{self.name}:{self.model_name}", "char", 1 if text else 0)


@lru_cache(maxsize=None)
def _reader(engine: str, version: str, lang: str, model_type: str, det_side: int):
    if engine == "rapidocr":
        return RapidOcrReader(version, lang, model_type, det_side)
    if engine == "tesseract":
        return TesseractReader()
    if engine == "fast_plate_ocr":
        return FastPlateReader()
    raise ValueError(f"unknown OCR engine {engine!r}")


def get_reader(cfg: OcrConfig, engine: str | None = None):
    return _reader(engine or cfg.engine, cfg.rapidocr_version, cfg.rapidocr_rec_lang, cfg.rapidocr_rec_model_type,
                   cfg.rapidocr_det_limit_side)


def read_plate(crop_bgr: np.ndarray, cfg: OcrConfig) -> OcrRead:
    """Primary engine; the fallback also reads when the primary is empty or unsure.

    The fallback's read replaces the primary's only when the primary is empty, or when the fallback matches a
    plate format and the primary does not. Both reads are kept so a reviewer can see the disagreement.
    """
    primary = get_reader(cfg).read(crop_bgr)
    if cfg.fallback == "none" or cfg.fallback == cfg.engine or (primary.text and primary.conf >= cfg.fallback_below_conf):
        return primary
    fallback = get_reader(cfg, cfg.fallback).read(crop_bgr)
    use_fallback = fallback.text and (
        not primary.text or (check_plate(fallback.text).regex_valid and not check_plate(primary.text).regex_valid))
    chosen, other = (fallback, primary) if use_fallback else (primary, fallback)
    chosen.alternatives = [other.to_dict() | {"alternatives": []}]
    return chosen


def crop_box(frame_bgr: np.ndarray, xyxy, pad: float) -> np.ndarray:
    """Crop a box with relative padding, clipped to the frame."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = xyxy
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    x1, y1 = max(int(np.floor(x1 - px)), 0), max(int(np.floor(y1 - py)), 0)
    x2, y2 = min(int(np.ceil(x2 + px)), w), min(int(np.ceil(y2 + py)), h)
    return frame_bgr[y1:y2, x1:x2].copy()


def sharpness(crop_bgr: np.ndarray) -> float:
    if crop_bgr.size == 0:
        return 0.0
    return float(cv2.Laplacian(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
