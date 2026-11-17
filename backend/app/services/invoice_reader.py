import logging
import re
import threading
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from typing import List, Optional

logger = logging.getLogger("campus_security.invoice_reader")

# Phase 7: reads a delivery invoice photo. OCR (RapidOCR primary, Tesseract fallback, as in
# scripts/test_ocr.py) turns the image into text rows; a deterministic parser turns rows into
# line items and totals. Nothing here classifies items or decides anything.

@dataclass
class OcrRow:
    text: str
    confidence: Optional[float] = None  # mean engine score of the row's fragments, 0..1

@dataclass
class OcrResult:
    engine: str  # RAPIDOCR or TESSERACT
    rows: List[OcrRow]
    confidence: Optional[float] = None

    @property
    def text(self) -> str:
        return "\n".join(r.text for r in self.rows)

@dataclass
class ParsedLine:
    line_no: int
    item_name: str
    quantity: Optional[int]
    unit_price: Optional[Decimal]
    amount: Optional[Decimal]
    confidence: Optional[float]
    readable: bool = True
    raw_text: str = ""

@dataclass
class ParsedInvoice:
    lines: List[ParsedLine] = field(default_factory=list)
    vendor: Optional[str] = None
    order_number: Optional[str] = None
    subtotal: Optional[Decimal] = None
    delivery_fee: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    total: Optional[Decimal] = None

# ---------------------------------------------------------------- OCR engines

_rapid_engine = None
_rapid_lock = threading.Lock()
RAPIDOCR_TEXT_SCORE = 0.3

def _load_rgb(image_path: Path):
    from PIL import Image, ImageOps
    with Image.open(image_path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")  # phone photos carry EXIF rotation

def _group_rows(fragments) -> List[OcrRow]:
    """fragments: (x_left, y_center, height, text, score). Same text line = overlapping y band."""
    rows = []
    for frag in sorted(fragments, key=lambda f: f[1]):
        if rows and abs(frag[1] - rows[-1]["y"]) <= 0.5 * max(frag[2], rows[-1]["h"]):
            row = rows[-1]
            row["frags"].append(frag)
            row["y"] = mean(f[1] for f in row["frags"])
            row["h"] = max(row["h"], frag[2])
        else:
            rows.append({"y": frag[1], "h": frag[2], "frags": [frag]})
    result = []
    for row in rows:
        frags = sorted(row["frags"], key=lambda f: f[0])
        scored = [(f[4], max(1, len(f[3].strip()))) for f in frags if f[4] is not None]
        weight = sum(w for _, w in scored)
        result.append(OcrRow(
            text="  ".join(f[3].strip() for f in frags if f[3].strip()),
            # weighted by text length: a lone low-score digit does not sink a well-read item name
            confidence=round(sum(s * w for s, w in scored) / weight, 4) if scored else None,
        ))
    return [r for r in result if r.text]

def run_rapidocr(image_path: Path) -> OcrResult:
    global _rapid_engine
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    img = np.asarray(_load_rgb(image_path))[:, :, ::-1].copy()  # RGB -> BGR (OpenCV order)
    with _rapid_lock:  # the ONNX sessions are created once and are not shared concurrently
        if _rapid_engine is None:
            # The default text_score (0.5) drops lone digits such as the Qty column; the per-row
            # confidence still carries the low score into screening (SCREENING_LINE_MIN_CONFIDENCE).
            _rapid_engine = RapidOCR(text_score=RAPIDOCR_TEXT_SCORE)
        result, _ = _rapid_engine(img)
    fragments = []
    for box, text, score in result or []:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        fragments.append((min(xs), (min(ys) + max(ys)) / 2, max(ys) - min(ys), str(text), float(score)))
    rows = _group_rows(fragments)
    scores = [f[4] for f in fragments]
    return OcrResult("RAPIDOCR", rows, round(mean(scores), 4) if scores else None)

def run_tesseract(image_path: Path) -> OcrResult:
    import pytesseract
    img = _load_rgb(image_path)
    data = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    lines = {}
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        conf = float(data["conf"][i])
        lines.setdefault(key, []).append((data["left"][i], data["width"][i], data["top"][i], word, conf / 100 if conf >= 0 else None))
    rows, all_scores = [], []
    for key in sorted(lines, key=lambda k: (mean(w[2] for w in lines[k]), k)):
        words = sorted(lines[key], key=lambda w: w[0])
        char_w = median(w[1] / max(1, len(w[3])) for w in words)
        text = words[0][3]
        for prev, cur in zip(words, words[1:]):
            gap = cur[0] - (prev[0] + prev[1])
            text += ("  " if gap > 2.5 * char_w else " ") + cur[3]  # keep column gaps visible
        scores = [w[4] for w in words if w[4] is not None]
        all_scores.extend(scores)
        rows.append(OcrRow(text=text, confidence=round(mean(scores), 4) if scores else None))
    return OcrResult("TESSERACT", rows, round(mean(all_scores), 4) if all_scores else None)

def read_image(image_path: Path) -> OcrResult:
    """RapidOCR first; Tesseract when RapidOCR fails, reads nothing, or yields no item line."""
    primary: Optional[OcrResult] = None
    try:
        primary = run_rapidocr(image_path)
        if primary.rows and parse_rows(primary.rows).lines:
            return primary
    except Exception as exc:  # noqa: BLE001 - any engine failure falls back
        logger.warning("RapidOCR failed on %s: %s", image_path, exc)
    try:
        fallback = run_tesseract(image_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tesseract failed on %s: %s", image_path, exc)
        fallback = None
    candidates = [r for r in (primary, fallback) if r is not None]
    if not candidates:
        return OcrResult("NONE", [], None)
    return max(candidates, key=lambda r: (len(parse_rows(r.rows).lines), len(r.rows)))

# ---------------------------------------------------------------- parser

_AMOUNT = r"(?:rs\.?\s*|inr\s*|₹\s*)?(?:\d{1,3}(?:,\d{3})+|\d+)[.,]\d{2}"
_ITEM_WITH_QTY = re.compile(
    r"^(?:\d{1,2}[.)]\s+)?(?P<name>.*?[A-Za-z].*?)\s+(?:qty[:\s]*)?(?:x\s*)?(?P<qty>\d{1,3})(?:\s*x)?"
    r"(?:\s+(?P<unit>" + _AMOUNT + r"))?\s+(?P<amount>" + _AMOUNT + r")$",
    re.IGNORECASE,
)
_ITEM_NO_QTY = re.compile(r"^(?:\d{1,2}[.)]\s+)?(?P<name>.*?[A-Za-z].*?)\s+(?P<amount>" + _AMOUNT + r")$", re.IGNORECASE)
_ANY_AMOUNT = re.compile(_AMOUNT, re.IGNORECASE)
_SUMMARY = [
    ("subtotal", re.compile(r"^\W*sub\s*-?\s*total\b", re.IGNORECASE)),
    ("delivery_fee", re.compile(r"^\W*(?:delivery|shipping|packing|packaging|platform|handling)\b", re.IGNORECASE)),
    ("tax", re.compile(r"^\W*(?:tax(?:es)?|gst|cgst|sgst|igst|vat)\b(?!\s*invoice)", re.IGNORECASE)),
    ("discount", re.compile(r"^\W*(?:discount|coupon|promo)\b", re.IGNORECASE)),
    ("total", re.compile(r"^\W*(?:grand\s+total|total(?:\s+(?:amount|payable|due))?|amount\s+(?:payable|due)|net\s+payable)\b", re.IGNORECASE)),
]
_HEADER_ITEM = re.compile(r"\b(?:item|items|description|particulars|product)\b", re.IGNORECASE)
_HEADER_COLS = re.compile(r"\b(?:qty|quantity|amount|amt|price|rate|total)\b", re.IGNORECASE)
_ORDER_NO = re.compile(r"\border[ \t]*(?:id|no\.?|number)?[ \t]*[:#]?[ \t]*#?[ \t]*([A-Z0-9]{1,6}-?[A-Z0-9-]{2,})", re.IGNORECASE)

def to_decimal(text: Optional[str]) -> Optional[Decimal]:
    if not text:
        return None
    clean = re.sub(r"(?i)rs\.?|inr|₹|\s", "", text)
    if re.fullmatch(r"\d+,\d{2}", clean):  # 56,00 decimal comma
        clean = clean.replace(",", ".")
    clean = clean.replace(",", "")
    try:
        return Decimal(clean).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None

def normalize_order_id(text: Optional[str]) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lstrip("#")).upper()

def _single_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def _summary_kind(text: str) -> Optional[str]:
    if not _ANY_AMOUNT.search(text):
        return None
    for kind, pattern in _SUMMARY:
        if pattern.search(text):
            return kind
    return None

_QTY_CELL = re.compile(r"^(?:x\s*)?(\d{1,3})(?:\s*x)?$", re.IGNORECASE)
_AMOUNT_CELL = re.compile(r"^" + _AMOUNT + r"$", re.IGNORECASE)

def _parse_cells(cells: List[str]) -> Optional[dict]:
    """Column cells as OCR separated them: [name, (qty), (unit price), amount]. A number inside the
    name cell stays part of the name ("Cigarettes pack of 20" is not quantity 20)."""
    if len(cells) < 2 or not _AMOUNT_CELL.match(cells[-1]):
        return None
    amount, rest = to_decimal(cells[-1]), cells[:-1]
    unit = qty = None
    if len(rest) >= 3 and _AMOUNT_CELL.match(rest[-1]) and _QTY_CELL.match(rest[-2]):
        unit, rest = to_decimal(rest[-1]), rest[:-1]
    if len(rest) >= 2 and _QTY_CELL.match(rest[-1]):
        qty, rest = int(_QTY_CELL.match(rest[-1]).group(1)), rest[:-1]
    name = re.sub(r"^\d{1,2}[.)]\s+", "", " ".join(rest)).strip(" .:-|")
    if not re.search(r"[A-Za-z]", name) or (qty is not None and not 1 <= qty <= 999):
        return None
    return {"name": name, "quantity": qty, "unit_price": unit, "amount": amount}

def parse_item_text(text: str) -> Optional[dict]:
    """'Cola 750 ml  2  80.00' -> name, qty, unit price, amount. None when the row has no amount."""
    cells = [c.strip() for c in re.split(r"\s{2,}|\t|\|", text) if c.strip()]
    if len(cells) >= 2:
        item = _parse_cells(cells)
        if item:
            return item
    t = _single_space(text)
    m = _ITEM_WITH_QTY.match(t)
    if m:
        qty = int(m.group("qty"))
        if 1 <= qty <= 999:
            return {"name": m.group("name").strip(" .:-|"), "quantity": qty,
                    "unit_price": to_decimal(m.group("unit")), "amount": to_decimal(m.group("amount"))}
    m = _ITEM_NO_QTY.match(t)
    if m:
        return {"name": m.group("name").strip(" .:-|"), "quantity": None, "unit_price": None,
                "amount": to_decimal(m.group("amount"))}
    return None

def parse_rows(rows: List[OcrRow]) -> ParsedInvoice:
    """
    Deterministic layout parser for printed single-column invoices:
    header block (vendor, order number) -> item table -> Subtotal / Delivery / Tax / TOTAL.
    Rows inside the item table that cannot be parsed become unreadable lines (screened REVIEW).
    """
    parsed = ParsedInvoice()
    all_text = "\n".join(r.text for r in rows)
    m = _ORDER_NO.search(all_text)
    if m:
        parsed.order_number = normalize_order_id(m.group(1))

    header_idx = next((i for i, r in enumerate(rows) if _HEADER_ITEM.search(r.text) and _HEADER_COLS.search(r.text)), None)
    for r in rows[: header_idx if header_idx is not None else len(rows)]:
        t = _single_space(r.text)
        if (re.search(r"[A-Za-z]{3}", t) and not re.search(r"(?i)invoice|order|date|bill|gstin|phone|tel", t)
                and not _ANY_AMOUNT.search(t)):
            parsed.vendor = t[:100]
            break

    in_items = header_idx is not None
    start = header_idx + 1 if header_idx is not None else 0
    seen_summary = False
    for r in rows[start:]:
        text = _single_space(r.text)
        kind = _summary_kind(text)
        if kind:
            seen_summary = True
            amounts = _ANY_AMOUNT.findall(text)
            value = to_decimal(amounts[-1]) if amounts else None
            if kind in ("delivery_fee", "tax", "discount"):
                current = getattr(parsed, kind)
                value = (current or Decimal("0.00")) + value if value is not None else current
            if kind == "total" and parsed.total is not None:
                continue  # first TOTAL row wins (a later "total items" line is not the bill total)
            setattr(parsed, kind, value)
            continue
        if seen_summary:
            continue  # footer
        item = parse_item_text(r.text)  # raw text: column gaps (double spaces) still visible
        if item and item["name"] and not _HEADER_ITEM.fullmatch(item["name"]):
            parsed.lines.append(ParsedLine(
                line_no=len(parsed.lines) + 1, item_name=item["name"][:150], quantity=item["quantity"],
                unit_price=item["unit_price"], amount=item["amount"], confidence=r.confidence, raw_text=text,
            ))
        elif in_items and re.search(r"[A-Za-z0-9]", text):
            if not _ANY_AMOUNT.search(text) and parsed.lines and re.search(r"[A-Za-z]{2}", text) and len(text) <= 40:
                parsed.lines[-1].item_name = (parsed.lines[-1].item_name + " " + text)[:150]  # wrapped name
            else:
                amounts = _ANY_AMOUNT.findall(text)
                parsed.lines.append(ParsedLine(
                    line_no=len(parsed.lines) + 1, item_name=text[:150] or "(unreadable)", quantity=None,
                    unit_price=None, amount=to_decimal(amounts[-1]) if amounts else None,
                    confidence=r.confidence, readable=False, raw_text=text,
                ))
    return parsed

def parse_text(text: str) -> ParsedInvoice:
    """Parser entry point for plain text (one row per line), e.g. tests or a typed message."""
    return parse_rows([OcrRow(line) for line in text.splitlines() if line.strip()])
