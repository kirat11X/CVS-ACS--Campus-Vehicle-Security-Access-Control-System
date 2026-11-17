#!/usr/bin/env python3
"""Generate a labelled set of FICTIONAL test invoices (PNG / JPG / PDF) plus manifest.json.

Output folder: <repo>/media/test_invoices/
    D-2048x_<slug>.png|jpg|pdf   the invoices
    manifest.json                expected screening result for every invoice
    README.txt                   human description of each case

The store names are made up (DEMO MART / QUICK BASKET) and every invoice carries the footer
"Sample invoice for demonstration - not a real order". Layout follows the mid-term slide 8
reference: store name, "TAX INVOICE . SAMPLE", "Order #D-.... + date" on one line, an
ITEM / QTY / AMOUNT table, then Subtotal, Delivery and TOTAL.

Expected verdicts follow the deterministic delivery policy (backend/app/services/delivery_policy.py):
    ALLOW  = food, beverage, stationery, personal care, electronics
    REVIEW = hazardous chemicals, medicine, unknown / unreadable, (and a totals mismatch)
    ALERT  = tobacco, alcohol, weapons
Overall verdict of an invoice = the worst line verdict, raised to at least REVIEW when the
printed TOTAL does not equal subtotal + delivery.

Idempotent and deterministic: fixed seed, same file names, files are overwritten.
Needs only Pillow + numpy (PDFs are written with Pillow, so they are raster-only: no text layer).

    python scripts/make_test_invoices.py [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SEED = 20481
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "media" / "test_invoices"

# ---------------------------------------------------------------------------------------------
# Policy table (mirrors backend/app/services/delivery_policy.py: category -> label, reason, verdict)
# ---------------------------------------------------------------------------------------------
POLICY: Dict[str, Tuple[str, str, str]] = {
    "FOOD": ("Food", "FOOD_OK", "ALLOW"),
    "BEVERAGE": ("Beverage", "BEVERAGE_OK", "ALLOW"),
    "STATIONERY": ("Stationery", "STATIONERY_OK", "ALLOW"),
    "PERSONAL_CARE": ("Personal care", "PERSONAL_CARE_OK", "ALLOW"),
    "ELECTRONICS": ("Electronics", "ELECTRONICS_OK", "ALLOW"),
    "HAZMAT": ("Hazardous chemical", "HAZMAT_NEEDS_APPROVAL", "REVIEW"),
    "MEDICINE": ("Medicine", "MEDICINE_NEEDS_APPROVAL", "REVIEW"),
    "UNKNOWN": ("Unknown", "UNKNOWN_CATEGORY", "REVIEW"),
    "TOBACCO": ("Tobacco", "TOBACCO_RESTRICTED", "ALERT"),
    "ALCOHOL": ("Alcohol", "ALCOHOL_RESTRICTED", "ALERT"),
    "WEAPON": ("Weapon", "WEAPON_RESTRICTED", "ALERT"),
}
SEVERITY = {"ALLOW": 0, "REVIEW": 1, "ALERT": 2}

# ---------------------------------------------------------------------------------------------
# Page geometry / fonts
# ---------------------------------------------------------------------------------------------
W = 900                      # invoice width in px
MARGIN = 40
X_ITEM = MARGIN              # item column, left aligned
X_QTY = 650                  # qty column, centred
X_AMT = W - MARGIN           # amount column, right aligned
ROW_H = 56
PAPER = (255, 255, 255)
INK = (18, 18, 18)
SOFT = (70, 70, 70)
RULE = (60, 60, 60)
ZEBRA = (240, 240, 240)
HEADER_FILL = (222, 222, 222)

SIZE_STORE = 60
SIZE_TITLE = 36
SIZE_BODY = 30               # item rows, order line, totals (>= 28 px at 900 px width)
SIZE_HEAD = 28               # table header, tagline, footer (never below 26 px)
SIZE_TOTAL = 40

PDF_DPI = 110.0              # 900 px -> ~589 pt (about A4 width)

# How the QTY cell is printed. A bare single digit ("4") is dropped by RapidOCR at its default text_score
# of 0.5 (recognition confidence is only about 0.3-0.5 for an isolated digit), so the default style adds a
# unit. Use --qty-style bare to generate the harder, strictly-numeric variant.
QTY_FORMATS = {"pc": "{q} pc", "pcs": "{q} pcs", "x": "x{q}", "bare": "{q}"}
QTY_STYLE = "pc"
FOOTER = "Sample invoice for demonstration \u00b7 not a real order"
TITLE = "TAX INVOICE \u00b7 SAMPLE"

FONT_ROOTS = [
    "/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
    str(Path.home() / ".local/share/fonts"), "C:/Windows/Fonts", "/Library/Fonts", "/System/Library/Fonts",
]


def find_font(candidates: Sequence[str]) -> str:
    """First existing file (by file name, searched under the usual font roots) from `candidates`."""
    for name in candidates:
        for root in FONT_ROOTS:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                if name in files:
                    return os.path.join(dirpath, name)
    raise FileNotFoundError("no usable TTF found for %s (install dejavu-sans-fonts or liberation-sans-fonts)"
                            % (list(candidates),))


FONT_REG = find_font(["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"])
FONT_BOLD = find_font(["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"])


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def fit_font(path: str, text: str, max_w: int, size: int, min_size: int) -> ImageFont.FreeTypeFont:
    """Largest font <= size whose rendering of `text` fits in max_w (never below min_size)."""
    while size > min_size:
        f = font(path, size)
        if f.getlength(text) <= max_w:
            return f
        size -= 1
    return font(path, min_size)


# ---------------------------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------------------------
@dataclass
class Item:
    name: str
    qty: int
    amount: str                 # line total (qty x unit price), as printed, e.g. "56.00"
    cat: str                    # key of POLICY
    note: str = ""

    @property
    def amt(self) -> Decimal:
        return Decimal(self.amount)


@dataclass
class Case:
    order_id: str
    slug: str
    title: str
    description: str
    items: List[Item]
    delivery: str
    date: str
    store: str = "DEMO MART"
    tagline: str = "Groceries & daily needs"
    printed_total: Optional[str] = None      # set only when the printed TOTAL is deliberately wrong
    style: str = "clean"                     # clean | degraded | photo | multipage
    formats: Tuple[str, ...] = ("png",)      # first entry is the primary file
    notes: str = ""

    @property
    def subtotal(self) -> Decimal:
        return sum((i.amt for i in self.items), Decimal("0.00"))

    @property
    def computed_total(self) -> Decimal:
        return self.subtotal + Decimal(self.delivery)

    @property
    def total(self) -> Decimal:
        return Decimal(self.printed_total) if self.printed_total is not None else self.computed_total

    @property
    def totals_match(self) -> bool:
        return self.total == self.computed_total

    @property
    def expected_overall(self) -> str:
        worst = max((POLICY[i.cat][2] for i in self.items), key=SEVERITY.get)
        if not self.totals_match and SEVERITY[worst] < SEVERITY["REVIEW"]:
            worst = "REVIEW"
        return worst


CASES: List[Case] = [
    Case(
        "D-20481", "clean", "Clean invoice, mixed risk",
        "Reference invoice from the mid-term slide: two plain items, a cleaner (hazmat) and cigarettes (tobacco).",
        [Item("Instant noodles 70g", 4, "56.00", "FOOD"),
         Item("Cola 750 ml", 2, "80.00", "BEVERAGE"),
         Item("Toilet cleaner 500 ml", 1, "99.00", "HAZMAT"),
         Item("Cigarettes pack of 20", 1, "350.00", "TOBACCO"),
         Item("Notebook A4 ruled", 2, "90.00", "STATIONERY")],
        "25.00", "14 Oct 2026", formats=("png", "pdf"),
        notes="Totals add up (675.00 + 25.00 = 700.00). Worst line is ALERT, so the invoice is ALERT.",
    ),
    Case(
        "D-20482", "allclear", "All-clear invoice",
        "Bread, milk, USB cable, shampoo and a pen set: every line is ALLOW and the totals match.",
        [Item("Bread loaf 400g", 1, "45.00", "FOOD"),
         Item("Milk 1 L", 2, "130.00", "FOOD"),
         Item("USB-C cable 1 m", 1, "199.00", "ELECTRONICS"),
         Item("Shampoo 180 ml", 1, "165.00", "PERSONAL_CARE"),
         Item("Pen set blue", 1, "60.00", "STATIONERY")],
        "30.00", "15 Oct 2026", formats=("png", "pdf"),
    ),
    Case(
        "D-20483", "alcohol", "Alcohol invoice",
        "A beer 6-pack with chips: the beer must raise an ALERT (ALCOHOL_RESTRICTED).",
        [Item("Beer 6-pack 330 ml", 1, "540.00", "ALCOHOL"),
         Item("Potato chips 100g", 2, "80.00", "FOOD")],
        "25.00", "16 Oct 2026", formats=("png", "pdf"),
    ),
    Case(
        "D-20484", "medicine_unknown", "Medicine plus unknown item",
        "Paracetamol (REVIEW, medicine) and a made-up product 'Zorblax widget' (REVIEW, unknown category).",
        [Item("Paracetamol 500mg strip", 1, "30.00", "MEDICINE"),
         Item("Zorblax widget", 1, "249.00", "UNKNOWN"),
         Item("Mineral water 1 L", 2, "40.00", "BEVERAGE")],
        "20.00", "17 Oct 2026", formats=("png", "pdf"),
    ),
    Case(
        "D-20485", "totals_mismatch", "Totals mismatch",
        "Every line is ALLOW but the lines sum to 540.00 and the printed TOTAL is 640.00 "
        "(should be 565.00 with delivery). Must be flagged, at least REVIEW.",
        [Item("Tea 250g", 1, "120.00", "BEVERAGE"),
         Item("Biscuits family pack", 3, "90.00", "FOOD"),
         Item("Toothpaste 150g", 2, "190.00", "PERSONAL_CARE"),
         Item("Earphones wired", 1, "140.00", "ELECTRONICS")],
        "25.00", "18 Oct 2026", printed_total="640.00", formats=("png", "pdf"),
        notes="Subtotal 540.00 + delivery 25.00 = 565.00, but TOTAL prints 640.00 (a 75.00 discrepancy).",
    ),
    Case(
        "D-20486", "hinglish_quickcommerce", "Hinglish / quick-commerce names",
        "Brand-only product names as seen on quick-commerce apps. Dettol Liquid should be hazmat (REVIEW) and "
        "Gold Flake Kings tobacco (ALERT).",
        [Item("Maggi Masala 4pk", 1, "56.00", "FOOD"),
         Item("Amul Taaza 500ml", 2, "54.00", "FOOD",
              note="Brand-only milk name; has no keyword in the policy table, so a pure keyword lookup gives UNKNOWN_CATEGORY."),
         Item("Kurkure Masala Munch 90g", 1, "20.00", "FOOD"),
         Item("Dettol Liquid 250ml", 1, "139.00", "HAZMAT",
              note="Brand-only antiseptic name; no hazmat keyword in the table, so keyword lookup alone gives UNKNOWN_CATEGORY (still REVIEW)."),
         Item("Gold Flake Kings 10s", 1, "190.00", "TOBACCO")],
        "15.00", "19 Oct 2026", store="QUICK BASKET", tagline="Delivered in 10 minutes",
        formats=("png", "pdf"),
    ),
    Case(
        "D-20487", "degraded_scan", "Degraded scan",
        "A simple all-ALLOW invoice, rotated 3 degrees with Gaussian blur (radius 1.2) and mild noise. "
        "Still readable; expected result equals the clean all-ALLOW case.",
        [Item("Biscuits 200g", 2, "40.00", "FOOD"),
         Item("Orange juice 1 L", 1, "110.00", "BEVERAGE"),
         Item("Notebook A4 ruled", 1, "45.00", "STATIONERY"),
         Item("Soap bar 100g", 3, "90.00", "PERSONAL_CARE"),
         Item("Phone charger 20W", 1, "399.00", "ELECTRONICS")],
        "25.00", "20 Oct 2026", style="degraded", formats=("png",),
    ),
    Case(
        "D-20488", "phone_photo", "Phone-photo style",
        "Photographed invoice: perspective skew, lighting gradient with a soft shadow, sensor noise and JPEG "
        "compression. Contains a bleach line (hazmat, REVIEW).",
        [Item("Basmati rice 1 kg", 1, "120.00", "FOOD"),
         Item("Atta 5 kg", 1, "245.00", "FOOD"),
         Item("Bleach 500 ml", 1, "85.00", "HAZMAT"),
         Item("Toothbrush soft", 2, "70.00", "PERSONAL_CARE")],
        "20.00", "21 Oct 2026", style="photo", formats=("jpg",),
    ),
    Case(
        "D-20489", "multipage", "Two-page invoice",
        "PDF only. Items continue on page 2 and the totals are on page 2. Page 1 is all ALLOW; page 2 holds "
        "phenyl (hazmat, REVIEW) and whisky (alcohol, ALERT), so a reader that stops after page 1 misses them.",
        [Item("Basmati rice 5 kg", 1, "480.00", "FOOD"),
         Item("Atta 5 kg", 1, "260.00", "FOOD"),
         Item("Sugar 1 kg", 2, "90.00", "FOOD"),
         Item("Salt 1 kg", 1, "28.00", "FOOD"),
         Item("Tea 500g", 1, "240.00", "BEVERAGE"),
         Item("Coffee 200g", 1, "310.00", "BEVERAGE"),
         Item("Notebook A4 ruled", 4, "180.00", "STATIONERY"),
         Item("Phenyl floor cleaner 1 L", 1, "130.00", "HAZMAT"),
         Item("Whisky 750 ml", 1, "1450.00", "ALCOHOL"),
         Item("Energy drink 250 ml", 2, "250.00", "BEVERAGE")],
        "40.00", "22 Oct 2026", style="multipage", formats=("pdf",),
        notes="6 items on page 1, 4 items plus Subtotal/Delivery/TOTAL on page 2.",
    ),
]
MULTIPAGE_SPLIT = 6          # items on page 1 of the multi-page case
MULTIPAGE_MIN_HEIGHT = 1100


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------
def money(value) -> str:
    return "{:,.2f}".format(Decimal(value))


def render_invoice(case: Case, items: Sequence[Item], page_no: int = 1, n_pages: int = 1,
                   show_totals: bool = True, min_height: Optional[int] = None) -> Image.Image:
    f_store = font(FONT_BOLD, SIZE_STORE)
    f_title = font(FONT_BOLD, SIZE_TITLE)
    f_body = font(FONT_REG, SIZE_BODY)
    f_head = font(FONT_BOLD, SIZE_HEAD)
    f_tag = font(FONT_REG, SIZE_HEAD)
    f_total = font(FONT_BOLD, SIZE_TOTAL)
    f_total_lbl = font(FONT_BOLD, SIZE_BODY + 2)

    canvas = Image.new("RGB", (W, 5000), PAPER)
    d = ImageDraw.Draw(canvas)

    def hrule(y: int, width: int = 2) -> None:
        d.line([(MARGIN, y), (W - MARGIN, y)], fill=RULE, width=width)

    y = 34
    d.text((W // 2, y), case.store, font=f_store, fill=INK, anchor="mt")
    y += 76
    d.text((W // 2, y), case.tagline, font=f_tag, fill=SOFT, anchor="mt")
    y += 46
    d.text((W // 2, y), TITLE, font=f_title, fill=INK, anchor="mt")
    y += 60
    hrule(y)
    y += 12
    d.text((X_ITEM, y + ROW_H // 2), "Order #%s" % case.order_id, font=f_body, fill=INK, anchor="lm")
    d.text((X_AMT, y + ROW_H // 2), case.date, font=f_body, fill=INK, anchor="rm")
    y += ROW_H
    if n_pages > 1:
        d.text((X_ITEM, y + ROW_H // 2 - 6), "Page %d of %d" % (page_no, n_pages), font=f_body, fill=INK, anchor="lm")
        y += ROW_H - 6
    hrule(y)
    y += 6
    # table header
    d.rectangle([MARGIN, y, W - MARGIN, y + ROW_H - 4], fill=HEADER_FILL)
    mid = y + (ROW_H - 4) // 2
    d.text((X_ITEM + 8, mid), "ITEM", font=f_head, fill=INK, anchor="lm")
    d.text((X_QTY, mid), "QTY", font=f_head, fill=INK, anchor="mm")
    d.text((X_AMT - 8, mid), "AMOUNT", font=f_head, fill=INK, anchor="rm")
    y += ROW_H
    # rows
    item_max_w = X_QTY - 60 - (X_ITEM + 8)
    for n, it in enumerate(items):
        if n % 2 == 1:
            d.rectangle([MARGIN, y, W - MARGIN, y + ROW_H - 1], fill=ZEBRA)
        mid = y + ROW_H // 2
        f_item = fit_font(FONT_REG, it.name, item_max_w, SIZE_BODY, 28)
        d.text((X_ITEM + 8, mid), it.name, font=f_item, fill=INK, anchor="lm")
        d.text((X_QTY, mid), QTY_FORMATS[QTY_STYLE].format(q=it.qty), font=f_body, fill=INK, anchor="mm")
        d.text((X_AMT - 8, mid), money(it.amount), font=f_body, fill=INK, anchor="rm")
        y += ROW_H
    hrule(y + 2)
    y += 14

    if show_totals:
        for label, value in (("Subtotal", case.subtotal), ("Delivery", Decimal(case.delivery))):
            d.text((X_ITEM + 8, y + ROW_H // 2), label, font=f_body, fill=INK, anchor="lm")
            d.text((X_AMT - 8, y + ROW_H // 2), money(value), font=f_body, fill=INK, anchor="rm")
            y += ROW_H
        hrule(y + 2, 3)
        y += 14
        d.text((X_ITEM + 8, y + 38), "TOTAL", font=f_total_lbl, fill=INK, anchor="lm")
        d.text((X_AMT - 8, y + 38), money(case.total), font=f_total, fill=INK, anchor="rm")
        y += 82
    else:
        d.text((W // 2, y + 26), "- continued on page %d -" % (page_no + 1), font=f_body, fill=SOFT, anchor="mm")
        y += 72

    footer_font = fit_font(FONT_REG, FOOTER, W - 2 * MARGIN, SIZE_HEAD, 26)
    foot_h = 90
    height = max(y + foot_h, min_height or 0)
    d.text((W // 2, height - 56), FOOTER, font=footer_font, fill=SOFT, anchor="mm")
    page = canvas.crop((0, 0, W, height))
    ImageDraw.Draw(page).rectangle([0, 0, W - 1, height - 1], outline=(190, 190, 190), width=2)
    return page


def add_noise(img: Image.Image, rng: np.random.Generator, sigma: float, chroma: float = 0.0) -> Image.Image:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    lum = rng.normal(0.0, sigma, arr.shape[:2])[..., None]
    arr = arr + lum
    if chroma > 0:
        arr = arr + rng.normal(0.0, chroma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def degrade_scan(base: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Rotate 3 degrees (on a light grey scanner bed), Gaussian blur radius 1.2, mild noise."""
    bed = (226, 226, 226)
    pad = 60
    canvas = Image.new("RGB", (base.width + 2 * pad, base.height + 2 * pad), bed)
    canvas.paste(base, (pad, pad))
    rotated = canvas.rotate(3, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=bed)
    blurred = rotated.filter(ImageFilter.GaussianBlur(radius=1.2))
    return add_noise(blurred, rng, sigma=7.0, chroma=2.0)


def _perspective_coeffs(dst: Sequence[Tuple[float, float]], src: Sequence[Tuple[float, float]]) -> List[float]:
    """Coefficients for Image.transform(PERSPECTIVE): output (dst) pixel -> source pixel."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.extend([u, v])
    return list(np.linalg.solve(np.array(rows, dtype=np.float64), np.array(rhs, dtype=np.float64)))


def photo_style(base: Image.Image, rng: np.random.Generator) -> Image.Image:
    """Invoice lying on a table, shot from an angle: perspective, shadow gradient, noise (JPEG at save)."""
    iw, ih = base.size
    cw, ch = iw + 200, ih + 260
    dst = [(58, 46), (cw - 34, 84), (cw - 104, ch - 44), (96, ch - 86)]       # tl, tr, br, bl
    src = [(0, 0), (iw, 0), (iw, ih), (0, ih)]
    coeffs = _perspective_coeffs(dst, src)
    bicubic = Image.Resampling.BICUBIC
    paper = base.transform((cw, ch), Image.Transform.PERSPECTIVE, coeffs, bicubic, fillcolor=PAPER)
    mask = Image.new("L", (iw, ih), 255).transform((cw, ch), Image.Transform.PERSPECTIVE, coeffs, bicubic)

    xx = np.linspace(0.0, 1.0, cw)[None, :]
    yy = np.linspace(0.0, 1.0, ch)[:, None]
    # wooden table: warm brown, horizontal grain, vignette
    grain = np.convolve(rng.normal(0.0, 1.0, ch), np.ones(7) / 7.0, mode="same")[:, None] * 9.0
    table = np.empty((ch, cw, 3), dtype=np.float32)
    for c, v in enumerate((96, 72, 54)):
        table[..., c] = v * (1.0 - 0.18 * (xx * 0.6 + yy * 0.4)) + grain
    table = np.clip(table, 0, 255).astype(np.uint8)
    bg = Image.fromarray(table, "RGB")
    # soft drop shadow of the sheet
    shadow = ImageChops.offset(mask.filter(ImageFilter.GaussianBlur(14)), 12, 16)
    dark = Image.new("RGB", (cw, ch), (20, 14, 10))
    bg = Image.composite(dark, bg, shadow.point(lambda v: int(v * 0.55)))
    scene = Image.composite(paper, bg, mask)

    # lighting: bright top-left, falling off to the bottom-right, plus a soft diagonal shadow band
    t = np.clip((xx * 0.7 + yy * 0.5 - 0.35) / 0.85, 0.0, 1.0)
    falloff = 0.26 * (t * t * (3.0 - 2.0 * t))
    band = 0.15 * np.exp(-(((xx * 0.9 + yy * 0.6) - 0.78) / 0.16) ** 2)
    light = (1.0 - falloff - band)[..., None]
    arr = np.asarray(scene, dtype=np.float32) * light
    # slight warm cast, as a phone camera under indoor light
    arr = arr * np.array([1.0, 0.97, 0.92], dtype=np.float32)
    shot = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    shot = shot.filter(ImageFilter.GaussianBlur(radius=0.7))
    return add_noise(shot, rng, sigma=4.0, chroma=1.5)


# ---------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------
def save_png(img: Image.Image, path: Path) -> None:
    img.save(path, format="PNG")


def save_jpg(img: Image.Image, path: Path) -> None:
    img.save(path, format="JPEG", quality=55, subsampling=2, optimize=False, progressive=False)


def save_pdf(pages: Sequence[Image.Image], path: Path) -> None:
    pages = [p.convert("RGB") for p in pages]
    fixed = time.gmtime(calendar.timegm((2026, 10, 20, 0, 0, 0)))   # pinned so the PDF bytes are reproducible
    pages[0].save(path, format="PDF", resolution=PDF_DPI, save_all=True, append_images=list(pages[1:]),
                  creationDate=fixed, modDate=fixed)


def build_case(case: Case, idx: int, out_dir: Path) -> Dict[str, object]:
    rng = np.random.default_rng(SEED + idx)
    stem = "%s_%s" % (case.order_id, case.slug)
    written: List[str] = []

    if case.style == "multipage":
        first, rest = case.items[:MULTIPAGE_SPLIT], case.items[MULTIPAGE_SPLIT:]
        pages = [render_invoice(case, first, 1, 2, False, MULTIPAGE_MIN_HEIGHT),
                 render_invoice(case, rest, 2, 2, True, MULTIPAGE_MIN_HEIGHT)]
        save_pdf(pages, out_dir / (stem + ".pdf"))
        written.append(stem + ".pdf")
    else:
        base = render_invoice(case, case.items)
        if case.style == "degraded":
            img = degrade_scan(base, rng)
        elif case.style == "photo":
            img = photo_style(base, rng)
        else:
            img = base
        for ext in case.formats:
            name = "%s.%s" % (stem, ext)
            if ext == "png":
                save_png(img, out_dir / name)
            elif ext == "jpg":
                save_jpg(img, out_dir / name)
            elif ext == "pdf":
                save_pdf([img], out_dir / name)
            else:
                raise ValueError(ext)
            written.append(name)

    lines = []
    for it in case.items:
        label, reason, verdict = POLICY[it.cat]
        line = {
            "item": it.name,
            "qty": it.qty,
            "amount": float(it.amt),
            "expected_category": it.cat,
            "expected_category_label": label,
            "expected_reason_code": reason,
            "expected_verdict": verdict,
        }
        if it.note:
            line["note"] = it.note
        lines.append(line)
    entry: Dict[str, object] = {
        "file": written[0],
        "files": written,
        "order_id": case.order_id,
        "case": case.slug,
        "title": case.title,
        "store": case.store,
        "date": case.date,
        "pages": 2 if case.style == "multipage" else 1,
        "lines": lines,
        "subtotal": float(case.subtotal),
        "delivery_fee": float(Decimal(case.delivery)),
        "total": float(case.total),
        "computed_total": float(case.computed_total),
        "totals_should_match": case.totals_match,
        "expected_overall": case.expected_overall,
        "description": case.description,
    }
    if case.notes:
        entry["notes"] = case.notes
    return entry


def readme_text(entries: Sequence[Dict[str, object]]) -> str:
    out = [
        "TEST INVOICES (fictional)",
        "=========================",
        "Generated by scripts/make_test_invoices.py (deterministic, seed %d). Re-running overwrites these files." % SEED,
        "Stores DEMO MART and QUICK BASKET do not exist. Every invoice carries the footer",
        "'Sample invoice for demonstration - not a real order'. Currency is INR (amounts shown without a symbol).",
        "",
        "Layout: store name, 'TAX INVOICE - SAMPLE', 'Order #ID' + date on one line, ITEM / QTY / AMOUNT table,",
        "then Subtotal, Delivery, TOTAL. 'amount' on a line is the line total (qty x unit price).",
        "Body text is 30 px DejaVu Sans on a 900 px wide page. The PDFs are raster-only (no text layer), so they",
        "must be rasterised and OCR'd like a photo.",
        "QTY cell is printed as e.g. '%s' (qty_style=%s): RapidOCR drops a bare single digit at its default" % (
            QTY_FORMATS[QTY_STYLE].format(q=4), QTY_STYLE),
        "text_score of 0.5. Regenerate with --qty-style bare for the harder, digit-only variant.",
        "",
        "Policy used for the expected results (backend/app/services/delivery_policy.py):",
        "  ALLOW  = food, beverage, stationery, personal care, electronics",
        "  REVIEW = hazardous chemical, medicine, unknown category, unreadable line, totals mismatch",
        "  ALERT  = tobacco, alcohol, weapon",
        "Overall = worst line verdict, raised to at least REVIEW when TOTAL != subtotal + delivery.",
        "manifest.json holds the same information in machine-readable form (cases[].lines[].expected_*).",
        "",
    ]
    for e in entries:
        out.append("%s  %s" % (e["order_id"], e["title"]))
        out.append("  files   : %s" % ", ".join(e["files"]))
        out.append("  store   : %s   date: %s   pages: %s" % (e["store"], e["date"], e["pages"]))
        out.append("  what    : %s" % e["description"])
        for ln in e["lines"]:
            out.append("    - %-28s x%-2d %9.2f  -> %-18s %-24s %s" % (
                ln["item"], ln["qty"], ln["amount"], ln["expected_category_label"],
                ln["expected_reason_code"], ln["expected_verdict"]))
        out.append("  totals  : subtotal %.2f + delivery %.2f -> printed TOTAL %.2f (computed %.2f) match=%s" % (
            e["subtotal"], e["delivery_fee"], e["total"], e["computed_total"], e["totals_should_match"]))
        out.append("  overall : %s" % e["expected_overall"])
        if e.get("notes"):
            out.append("  notes   : %s" % e["notes"])
        out.append("")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    global QTY_STYLE
    ap =argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--qty-style", choices=sorted(QTY_FORMATS), default=QTY_STYLE,
                    help="how the QTY cell is printed (default: %(default)s; 'bare' = just the digit)")
    args = ap.parse_args(argv)
    QTY_STYLE = args.qty_style
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = [build_case(case, i, out_dir) for i, case in enumerate(CASES)]
    manifest = {
        "generator": "scripts/make_test_invoices.py",
        "seed": SEED,
        "currency": "INR",
        "qty_style": QTY_STYLE,
        "qty_cell_example": QTY_FORMATS[QTY_STYLE].format(q=4),
        "policy_source": "backend/app/services/delivery_policy.py",
        "overall_rule": "worst line verdict (ALLOW<REVIEW<ALERT); at least REVIEW when totals_should_match is false",
        "cases": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "README.txt").write_text(readme_text(entries) + "\n", encoding="utf-8")

    for e in entries:
        print("%s  %-24s overall=%-6s match=%-5s files=%s" % (
            e["order_id"], e["case"], e["expected_overall"], e["totals_should_match"], ",".join(e["files"])))
    print("wrote %d cases to %s" % (len(entries), out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
