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
    restaurant: Optional[str] = None
    platform: Optional[str] = None
    outlet_location: Optional[str] = None
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

def extract_pdf_digital_text(pdf_path: Path) -> Optional[OcrResult]:
    """
    Extracts selectable digital text directly from a PDF invoice using pdftotext.
    Returns an OcrResult with confidence=1.0 and engine='PDF_DIGITAL' if digital text
    is found (eliminates OCR noise completely). Returns None if the PDF is scanned/empty.
    """
    import subprocess
    try:
        res = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        raw = res.stdout
        lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
        # Check if it has genuine digital text (> 2 lines and >= 25 chars)
        if len(lines) >= 2 and sum(len(l) for l in lines) >= 25:
            rows = [OcrRow(text=l, confidence=1.0) for l in lines]
            return OcrResult("PDF_DIGITAL", rows, confidence=1.0)
    except Exception as exc:
        logger.debug("pdftotext extraction not available or failed for %s: %s", pdf_path, exc)
    return None


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

_CURRENCY_PREFIX = r"(?:rs\.?\s*|inr\s*|[₹弄Ff¥?]\s*)"
_AMOUNT = r"(?:" + _CURRENCY_PREFIX + r")?(?:\d{1,3}(?:,\d{3})+|\d+)[.,]\d{2}"
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

def split_concatenated_prices(text: str) -> str:
    """
    Splits fused adjacent prices (MRP and discounted price) in summary lines,
    e.g. 'Item Total 184165' -> 'Item Total 184 165', 'Total Bill 223174' -> 'Total Bill 223 174'.
    """
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        if re.search(r"(?i)\b(?:total|bill|item|summary|fee|pay|paid)\b", line):
            # Check 6 digits: 3 + 3 (e.g. 184165 -> 184 165, 223174 -> 223 174)
            def repl6(m: re.Match) -> str:
                a, b = m.group(1), m.group(2)
                if int(a) >= int(b):
                    return f"{a} {b}"
                return m.group(0)

            line = re.sub(r"\b(\d{3})(\d{3})\b", repl6, line)

            # Check 5 digits: 3 + 2 (e.g. 12085 -> 120 85)
            def repl5(m: re.Match) -> str:
                a, b = m.group(1), m.group(2)
                if int(a) >= int(b):
                    return f"{a} {b}"
                return m.group(0)

            line = re.sub(r"\b(\d{3})(\d{2})\b", repl5, line)

            # Check 4 digits: 2 + 2 (e.g. 9570 -> 95 70)
            def repl4(m: re.Match) -> str:
                a, b = m.group(1), m.group(2)
                if int(a) > int(b):
                    return f"{a} {b}"
                return m.group(0)

            line = re.sub(r"\b(\d{2})(\d{2})\b", repl4, line)
        lines.append(line)
    return "\n".join(lines)


def normalize_phantom_currency_artifacts(text: str) -> str:
    """
    Detects if OCR misread the Indian Rupee symbol '₹' as a leading digit ('2', '3', or '7')
    consistently across fees and bill totals (e.g. Delivery Fee 230 FREE, Handling Fee 212 FREE,
    Total Bill 2741 2130) and strips the artifact to recover authentic amounts.
    """
    if not text:
        return ""
    text = split_concatenated_prices(text)

    # 1. Detect if 2, 3, or 7 is acting as a phantom Rupee symbol across the receipt
    phantom_digit = None
    m_fee = re.search(r"(?i)(?:delivery|handling)\s*fee\s*[:\s]*([237])\d{1,2}\b", text)
    m_tot = re.search(r"(?i)(?:total\s*bill|item\s*total|bill\s*total)\s*[:\s]*([237])\d{3,4}\s+([237])\d{3,4}\b", text)
    if m_fee:
        phantom_digit = m_fee.group(1)
    elif m_tot and m_tot.group(1) == m_tot.group(2):
        phantom_digit = m_tot.group(1)

    lines = []
    p = phantom_digit
    for l in text.splitlines():
        if p:
            if re.search(r"(?i)(?:delivery|handling|platform)\s*fee", l):
                l = re.sub(rf"\b{p}(\d{{1,2}}\b)", r"\1", l)
            elif re.search(r"(?i)(?:total|bill|item\s*total|sub\s*-?total)", l):
                l = re.sub(rf"\b{p}(\d{{2,4}}\b)", r"\1", l)
            elif re.search(r"(?i)cable|charging|portronics|phone|usb|\bunit\b|\bpack\b", l):
                l = re.sub(rf"\b{p}(\d{{2,4}}\b)", r"\1", l)
        # Normalize "R9" or "#9" -> "9" on fee or item price lines
        if re.search(r"(?i)(?:fee|pack|paneer|eggs?)\s+[R#]\s*(\d+)", l):
            l = re.sub(r"(?i)((?:fee|pack|paneer|eggs?)\s+)[R#]\s*(\d+)", r"\1\2", l)
        lines.append(l)
    return "\n".join(lines)


def normalize_currency_artifacts(text: str) -> str:
    """
    Normalize currency artifacts (弄, F, ¥, ?, Rs., INR) only when directly preceding numeric amounts.
    Preserves normal text and words like 'Fortune', 'Faasos', or 'Order #F-1234'.
    """
    if not text:
        return ""
    return re.sub(r"(?i)(^|[\s:|(])(?:rs\.?|inr|[弄F¥?])\s*(?=\d)", r"\1₹", text)

def to_decimal(text: Optional[str]) -> Optional[Decimal]:
    if not text:
        return None
    # Strip currency symbols and artifacts only when directly preceding digits
    clean = re.sub(r"(?i)(?:rs\.?|inr|[₹弄Ff¥?#Rrz])(?=\s*\d)", "", text)
    clean = re.sub(r"\s", "", clean)
    if re.fullmatch(r"\d+,\d{2}", clean):  # 56,00 decimal comma
        clean = clean.replace(",", ".")
    clean = clean.replace(",", "")
    clean = re.sub(r"^[^\d]+", "", clean)
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
    normalized_text = normalize_currency_artifacts(text)
    cells = [c.strip() for c in re.split(r"\s{2,}|\t|\|", normalized_text) if c.strip()]
    if len(cells) >= 2:
        item = _parse_cells(cells)
        if item:
            return item
    t = _single_space(normalized_text)
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

def reconcile_phantom_currency_digits(parsed: ParsedInvoice) -> ParsedInvoice:
    """
    Arithmetic sanity check to detect and strip phantom leading '2', '3', or '7' digits
    caused by Rupee (₹) OCR misreads when line arithmetic (qty * unit_price), grand total,
    or subtotal reconciliation confirms it.
    """
    # 0. Sanity check: individual item amount cannot exceed the entire invoice bill total!
    ref_total = parsed.total or parsed.subtotal
    if ref_total is not None and ref_total > Decimal("0.00"):
        max_plausible = max(ref_total * Decimal("1.6"), ref_total + (parsed.discount or Decimal("500.00")))
        for line in parsed.lines:
            if line.amount is not None and line.amount > ref_total:
                s_amt = f"{line.amount:.2f}"
                if s_amt[0] in ("2", "3", "7") and len(s_amt) > 4:
                    try:
                        cand_amt = Decimal(s_amt[1:])
                        if cand_amt <= max_plausible:
                            logger.info(
                                "Stripped phantom leading '%s' because amount %s exceeded bill total %s: %s -> %s",
                                s_amt[0], line.amount, ref_total, line.amount, cand_amt
                            )
                            line.amount = cand_amt
                            if line.unit_price is None or line.unit_price == line.amount or line.unit_price > ref_total:
                                line.unit_price = (cand_amt / Decimal(line.quantity or 1)).quantize(Decimal("0.01"))
                    except Exception:
                        pass

    # 0b. Global phantom digit strip: when total and all line amounts share a leading '2', '3', or '7'
    if parsed.total is not None and parsed.lines and parsed.total >= Decimal("1000.00"):
        s_tot = f"{parsed.total:.2f}"
        if s_tot[0] in ("2", "3", "7") and len(s_tot.split(".")[0]) >= 4:
            cand_tot = Decimal(s_tot[1:])
            if cand_tot > Decimal("0.00"):
                all_share = all(
                    l.amount is not None and f"{l.amount:.2f}".startswith(s_tot[0]) and len(f"{l.amount:.2f}".split(".")[0]) >= 4
                    for l in parsed.lines
                )
                if all_share:
                    cand_sum = sum(Decimal(f"{l.amount:.2f}"[1:]) for l in parsed.lines)
                    expected_tot = (
                        cand_sum
                        + (parsed.delivery_fee or Decimal("0.00"))
                        + (parsed.tax or Decimal("0.00"))
                        - (parsed.discount or Decimal("0.00"))
                    )
                    if abs(cand_tot - expected_tot) <= Decimal("0.05"):
                        logger.info("Global phantom digit '%s' stripped across entire invoice: total %s -> %s", s_tot[0], parsed.total, cand_tot)
                        parsed.total = cand_tot
                        if parsed.subtotal is not None and f"{parsed.subtotal:.2f}".startswith(s_tot[0]):
                            parsed.subtotal = Decimal(f"{parsed.subtotal:.2f}"[1:])
                        for l in parsed.lines:
                            l.amount = Decimal(f"{l.amount:.2f}"[1:])
                            if l.unit_price is not None and f"{l.unit_price:.2f}".startswith(s_tot[0]):
                                l.unit_price = Decimal(f"{l.unit_price:.2f}"[1:])

    # 1. Line-item arithmetic verification: qty * unit_price == amount
    for line in parsed.lines:
        if line.quantity is not None and line.unit_price is not None and line.amount is not None:
            expected = (Decimal(line.quantity) * line.unit_price).quantize(Decimal("0.01"))
            if abs(line.amount - expected) > Decimal("0.02"):
                # Check if amount has a phantom leading 2, 3, or 7 (e.g. ₹20.00 read as 320.00 or 220.00)
                s_amt = f"{line.amount:.2f}"
                if s_amt[0] in ("2", "3", "7") and len(s_amt) > 4:
                    try:
                        cand_amt = Decimal(s_amt[1:])
                        if abs(cand_amt - expected) <= Decimal("0.02"):
                            logger.info("Stripped phantom leading '%s' from line %d amount: %s -> %s",
                                        s_amt[0], line.line_no, line.amount, cand_amt)
                            line.amount = cand_amt
                    except Exception:
                        pass
                # Check if unit_price has a phantom leading 2, 3, or 7
                s_up = f"{line.unit_price:.2f}"
                if abs(line.amount - expected) > Decimal("0.02") and s_up[0] in ("2", "3", "7") and len(s_up) > 4:
                    try:
                        cand_up = Decimal(s_up[1:])
                        if abs(Decimal(line.quantity) * cand_up - line.amount) <= Decimal("0.02"):
                            logger.info("Stripped phantom leading '%s' from line %d unit_price: %s -> %s",
                                        s_up[0], line.line_no, line.unit_price, cand_up)
                            line.unit_price = cand_up
                    except Exception:
                        pass

    # 2. Subtotal and grand total reconciliation
    target_subtotal = parsed.subtotal
    if target_subtotal is None and parsed.total is not None:
        target_subtotal = (
            parsed.total
            - (parsed.delivery_fee or Decimal("0.00"))
            - (parsed.tax or Decimal("0.00"))
            + (parsed.discount or Decimal("0.00"))
        )

    if target_subtotal is not None and parsed.lines:
        amounts = [l.amount for l in parsed.lines if l.amount is not None]
        if len(amounts) == len(parsed.lines):
            current_sum = sum(amounts, Decimal("0.00"))
            if abs(current_sum - target_subtotal) > Decimal("0.02"):
                # Search for a single line with a phantom leading 2, 3, or 7 that resolves the mismatch
                repaired = False
                for line in parsed.lines:
                    s_amt = f"{line.amount:.2f}"
                    if s_amt[0] in ("2", "3", "7") and len(s_amt) > 4:
                        try:
                            cand_amt = Decimal(s_amt[1:])
                            new_sum = current_sum - line.amount + cand_amt
                            if abs(new_sum - target_subtotal) <= Decimal("0.02"):
                                logger.info("Subtotal reconciled: stripped phantom '%s' from line %s (%s -> %s)",
                                            s_amt[0], line.item_name, line.amount, cand_amt)
                                line.amount = cand_amt
                                current_sum = new_sum
                                repaired = True
                                break
                        except Exception:
                            pass

                # If no line was repaired, check if subtotal or grand total itself has a phantom leading digit
                if not repaired:
                    if parsed.subtotal is not None:
                        s_sub = f"{parsed.subtotal:.2f}"
                        if s_sub[0] in ("2", "3", "7") and len(s_sub) > 4:
                            try:
                                cand_sub = Decimal(s_sub[1:])
                                if abs(cand_sub - current_sum) <= Decimal("0.02"):
                                    logger.info("Subtotal reconciled: stripped phantom '%s' from subtotal (%s -> %s)",
                                                s_sub[0], parsed.subtotal, cand_sub)
                                    parsed.subtotal = cand_sub
                            except Exception:
                                pass
                    if parsed.total is not None:
                        expected_total = (
                            current_sum
                            + (parsed.delivery_fee or Decimal("0.00"))
                            + (parsed.tax or Decimal("0.00"))
                            - (parsed.discount or Decimal("0.00"))
                        )
                        s_tot = f"{parsed.total:.2f}"
                        if s_tot[0] in ("2", "3", "7") and len(s_tot) > 4:
                            try:
                                cand_tot = Decimal(s_tot[1:])
                                if abs(cand_tot - expected_total) <= Decimal("0.02"):
                                    logger.info("Total reconciled: stripped phantom '%s' from grand total (%s -> %s)",
                                                s_tot[0], parsed.total, cand_tot)
                                    parsed.total = cand_tot
                            except Exception:
                                pass

    return parsed

def parse_mobile_order_layout(rows: List[OcrRow]) -> ParsedInvoice:
    """
    Parser for modern Indian mobile app delivery screenshots (Blinkit, Swiggy Instamart,
    Zepto, Zomato) where items span 2 rows without traditional column headers:
      Row 1: <Item Name>  <Price>
      Row 2: <Weight/Specification> · <Quantity>unit
    Followed by a Bill summary block ('Items total', 'Handling fee', 'Delivery fee', 'You pay').
    """
    parsed = ParsedInvoice()
    raw_combined = "\n".join(r.text.strip() for r in rows if r.text.strip())
    if not raw_combined:
        return parsed

    normalized_combined = normalize_phantom_currency_artifacts(raw_combined)
    raw_texts = [line.strip() for line in normalized_combined.splitlines() if line.strip()]

    # 1. Detect platform/vendor from app UI markers
    all_low = normalized_combined.lower()
    if (
        "zepto" in all_low
        or "credit note" in all_low
        or "creditnote" in all_low
        or "order again" in all_low
        or "orderagain" in all_low
        or re.search(r"#[A-Z]{8,15}\d{4,6}\b", normalized_combined)
    ):
        parsed.vendor = "Zepto"
        parsed.platform = "Zepto"
    elif "swiggy" in all_low or "instamart" in all_low:
        parsed.vendor = "Swiggy Instamart"
        parsed.platform = "Swiggy"
    elif "blinkit" in all_low or "delivered in" in all_low:
        parsed.vendor = "Blinkit"
        parsed.platform = "Blinkit"
    elif "zomato" in all_low:
        parsed.vendor = "Zomato"
        parsed.platform = "Zomato"

    # Order ID extraction
    m_oid = re.search(r"#?([A-Z]{8,15}\d{4,6})\b", normalized_combined)
    if m_oid:
        parsed.order_number = m_oid.group(1)

    # 2. Identify Bill summary section
    summary_idx = next(
        (i for i, r in enumerate(raw_texts) if re.search(r"(?i)bill\s*summary|order\s*summary|payment\s*details", r)),
        len(raw_texts),
    )
    items_start = next(
        (i for i, r in enumerate(raw_texts[:summary_idx]) if re.search(r"(?i)\b\d+\s*items?\s*(?:in\s*order)?\b", r)),
        -1,
    )
    start_i = items_start + 1 if items_start != -1 else 0

    i = start_i
    while i < summary_idx:
        line = raw_texts[i]
        # Skip status bar lines like 1:04M 64 or phone headers
        if re.search(r"^\d{1,2}:\d{2}|\b(?:am|pm)\b|\b\d{1,2}%\b", line, re.IGNORECASE):
            i += 1
            continue
        if re.search(r"(?i)order\s*#|order\s*details|delivered|get help", line):
            i += 1
            continue

        # Skip summary lines if they appear early
        if re.search(r"(?i)^(?:sub\s*-?total|total|grand\s+total|tax|delivery|handling|items?\s+total|you\s+pay)", line.strip()):
            i += 1
            continue

        # Match Item Name followed by Price at line end: e.g. TataTeaGold-AssamTea  180 or Saffola  #20
        m = re.search(r"^(.*?)\s+([₹￥弄F#Rz\?]?\s*r?s?\.?\s*\d{1,5}(?:\.\d{2})?)$", line, re.IGNORECASE)
        if m and re.search(r"[A-Za-z]", m.group(1)):
            name = m.group(1).strip(" -:·")
            price_dec = to_decimal(m.group(2))
            qty = 1

            # Check next lines for continuation of name or unit
            if i + 1 < summary_idx:
                next_l = raw_texts[i + 1]
                m_q = re.search(r"(\d+)\s*(?:unit|piece|item|x|qty)s?\b", next_l, re.IGNORECASE)
                if m_q:
                    qty = int(m_q.group(1))
                    i += 1
                elif re.search(r"(?i)cable|lightning|adapter|usb|paneer|eggs?|milk|bread", next_l) and not re.search(r"^\d+$", next_l):
                    clean_next = re.sub(r"\s+\d{2,5}$", "", next_l).strip(" -:·")
                    name = f"{name} {clean_next}"
                    i += 1
                elif not re.search(r"\d{2,}", next_l) and len(next_l) < 30:
                    i += 1  # packaging / unit weight line

            parsed.lines.append(
                ParsedLine(
                    line_no=len(parsed.lines) + 1,
                    item_name=name,
                    quantity=qty,
                    unit_price=price_dec,
                    amount=price_dec,
                    confidence=1.0,
                    readable=True,
                    raw_text=line,
                )
            )
        i += 1

    # 3. Bill summary totals
    handling_fee = Decimal("0.00")
    for r in raw_texts[summary_idx:]:
        clean = normalize_currency_artifacts(r)
        if re.search(r"(?i)items?\s+total|sub\s*-?total", clean):
            amts = re.findall(r"\d+(?:\.\d{2})?", clean)
            if amts:
                parsed.subtotal = Decimal(amts[-1])
        elif re.search(r"(?i)you\s+pay|grand\s+total|final\s+total|total\s+bill|\btotal\b", clean):
            amts = re.findall(r"\d+(?:\.\d{2})?", clean)
            if amts:
                parsed.total = Decimal(amts[-1])
        elif re.search(r"(?i)delivery\s+fee", clean):
            if "free" in clean.lower():
                parsed.delivery_fee = Decimal("0.00")
            else:
                amts = re.findall(r"\d+(?:\.\d{2})?", clean)
                if amts:
                    parsed.delivery_fee = Decimal(amts[-1])
        elif re.search(r"(?i)handling\s+fee", clean):
            if "free" in clean.lower():
                pass
            else:
                amts = re.findall(r"\d+(?:\.\d{2})?", clean)
                if amts:
                    handling_fee = Decimal(amts[-1])

    if handling_fee > Decimal("0.00"):
        parsed.delivery_fee = (parsed.delivery_fee or Decimal("0.00")) + handling_fee

    return reconcile_phantom_currency_digits(parsed)


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
        # Avoid phone status bar junk like '8:48... 中 B.ll Ve 54%'
        if re.search(r"^\d{1,2}:\d{2}|\b(?:am|pm)\b|\b\d{1,2}%\b|\.ll\b", t, re.IGNORECASE):
            continue
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

    readable_count = sum(1 for l in parsed.lines if l.readable)
    if header_idx is None or readable_count == 0:
        mobile_parsed = parse_mobile_order_layout(rows)
        if len(mobile_parsed.lines) > readable_count:
            return mobile_parsed

    return reconcile_phantom_currency_digits(parsed)

def parse_text(text: str) -> ParsedInvoice:
    """Parser entry point for plain text (one row per line), e.g. tests or a typed message."""
    return parse_rows([OcrRow(line) for line in text.splitlines() if line.strip()])
