#!/usr/bin/env python3
"""OCR-friendliness check for media/test_invoices (RapidOCR only; does not touch the backend).

For every case it OCRs the primary file (PDFs are rasterised with pdftoppm at 150 dpi), then
checks item names, quantities, line amounts, Subtotal / Delivery / TOTAL, order id and footer
against manifest.json. Quantities and amounts are located geometrically (same text line as the
item, measured along the item's own baseline), so rotated or skewed images are handled.

    python scripts/check_test_invoices_ocr.py                 # cases D-20481 D-20482 D-20487
    python scripts/check_test_invoices_ocr.py --all           # every case
    python scripts/check_test_invoices_ocr.py D-20485 --dump  # chosen cases, print raw OCR lines
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
INV_DIR = REPO_ROOT / "media" / "test_invoices"
DEFAULT_CASES = ["D-20481", "D-20482", "D-20487"]

Det = Tuple[np.ndarray, str, float]          # (4x2 polygon, text, score)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def to_money(s: str) -> Optional[float]:
    t = s.replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(?:rs\.?|inr|₹)?(\d+\.\d{2})", t, flags=re.I)
    return float(m.group(1)) if m else None


def ocr_pages(engine, path: Path) -> List[List[Det]]:
    images = [path]
    tmp = None
    if path.suffix.lower() == ".pdf":
        tmp = tempfile.TemporaryDirectory()
        subprocess.run(["pdftoppm", "-r", "150", "-png", str(path), str(Path(tmp.name) / "p")], check=True)
        images = sorted(Path(tmp.name).glob("p*.png"))
    pages: List[List[Det]] = []
    for img in images:
        result, _ = engine(str(img))
        dets: List[Det] = []
        for box, text, score in (result or []):
            dets.append((np.array(box, dtype=float), text, float(score)))
        pages.append(dets)
    if tmp:
        tmp.cleanup()
    return pages


def centre(box: np.ndarray) -> np.ndarray:
    return box.mean(axis=0)


def page_direction(dets: List[Det]) -> np.ndarray:
    """Unit vector along the text lines of the page: median angle of the long boxes (short boxes are noisy)."""
    angles = []
    for box, _t, _s in dets:
        v = box[1] - box[0]
        if np.linalg.norm(v) > 150 and np.linalg.norm(v) > 3 * np.linalg.norm(box[3] - box[0]):
            angles.append(np.arctan2(v[1], v[0]))
    a = float(np.median(angles)) if angles else 0.0
    return np.array([np.cos(a), np.sin(a)])


def on_same_line(anchor: np.ndarray, dets: List[Det], tol: float) -> List[Tuple[float, Det]]:
    """Detections lying on the anchor's text line, ordered by distance along it (left to right)."""
    u = page_direction(dets)
    n = np.array([-u[1], u[0]])
    c0 = centre(anchor)
    out = []
    for d in dets:
        c = centre(d[0])
        if d[0] is anchor:
            continue
        s, p = float((c - c0) @ u), float((c - c0) @ n)
        if abs(p) <= tol:
            out.append((s, d))
    return sorted(out, key=lambda t: t[0])


def best_item(name: str, dets: List[Det]) -> Tuple[Optional[Det], float]:
    want = norm(name)
    best, best_r = None, 0.0
    for d in dets:
        got = norm(d[1])
        r = difflib.SequenceMatcher(None, want, got).ratio()
        if want and want in got:
            r = max(r, 0.97)
        if r > best_r:
            best, best_r = d, r
    return best, best_r


def find_label(label: str, dets: List[Det]) -> Optional[Det]:
    for d in dets:
        if norm(d[1]) == norm(label):
            return d
    cand = [d for d in dets if norm(label) in norm(d[1])]
    return cand[0] if cand else None


def row_numbers(anchor: Det, dets: List[Det]) -> Tuple[List[str], Optional[float]]:
    """Integer-like texts and the right-most money value to the right of the anchor on its line."""
    height = float(np.linalg.norm(anchor[0][3] - anchor[0][0]))
    ints, money = [], None
    for _s, d in [x for x in on_same_line(anchor[0], dets, tol=height * 0.8) if x[0] > 0]:
        t = d[1].strip()
        q = re.fullmatch(r"x?\s*(\d{1,3})\s*(?:pcs?|x)?", t, flags=re.I)     # "4", "x4", "4 pc", "4 pcs"
        if q:
            ints.append(q.group(1).lstrip("0") or "0")
        m = to_money(t)
        if m is not None:
            money = m
    return ints, money


def check_case(engine, entry: Dict, fname: str, dump: bool) -> Tuple[int, int, List[str]]:
    path = INV_DIR / fname
    pages = ocr_pages(engine, path)
    all_dets = [d for p in pages for d in p]
    ok_n = tot_n = 0
    notes: List[str] = []

    def record(ok: bool, msg: str) -> None:
        nonlocal ok_n, tot_n
        tot_n += 1
        ok_n += 1 if ok else 0
        if not ok:
            notes.append(msg)

    if dump:
        for pi, p in enumerate(pages):
            for d in sorted(p, key=lambda x: (centre(x[0])[1], centre(x[0])[0])):
                print("    p%d %-45s %.2f" % (pi + 1, d[1], d[2]))

    text_all = " ".join(norm(d[1]) for d in all_dets)
    record(norm(entry["order_id"]) in text_all, "order id %s not read" % entry["order_id"])
    record("notarealorder" in text_all, "footer not read")

    for ln in entry["lines"]:
        det, ratio, page_dets = None, 0.0, []
        for p in pages:
            d, r = best_item(ln["item"], p)
            if d is not None and r > ratio:
                det, ratio, page_dets = d, r, p
        name_ok = det is not None and ratio >= 0.9
        record(name_ok, "item '%s' read as '%s' (%.2f)" % (ln["item"], det[1] if det else None, ratio))
        if det is None:
            record(False, "qty of '%s' not found" % ln["item"])
            record(False, "amount of '%s' not found" % ln["item"])
            continue
        ints, money = row_numbers(det, page_dets)
        record(bool(ints) and ints[0] == str(ln["qty"]),
               "qty of '%s': expected %s read %s" % (ln["item"], ln["qty"], ints))
        record(money is not None and abs(money - ln["amount"]) < 0.005,
               "amount of '%s': expected %.2f read %s" % (ln["item"], ln["amount"], money))

    for label, key in (("Subtotal", "subtotal"), ("Delivery", "delivery_fee"), ("TOTAL", "total")):
        found = None
        for p in pages:
            d = find_label(label, p)
            if d is not None:
                found = (d, p)
        if found is None:
            record(False, "%s label not found" % label)
            continue
        _ints, money = row_numbers(found[0], found[1])
        record(money is not None and abs(money - entry[key]) < 0.005,
               "%s: expected %.2f read %s" % (label, entry[key], money))
    return ok_n, tot_n, notes


def main() -> int:
    global INV_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*", help="order ids (default: %s)" % " ".join(DEFAULT_CASES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dump", action="store_true", help="print the raw OCR lines")
    ap.add_argument("--dir", type=Path, default=INV_DIR, help="folder holding manifest.json and the invoices")
    ap.add_argument("--variants", action="store_true", help="check every file of a case (PNG and PDF), not just the first")
    args = ap.parse_args()
    INV_DIR = args.dir

    manifest = json.loads((INV_DIR / "manifest.json").read_text(encoding="utf-8"))
    wanted = [e["order_id"] for e in manifest["cases"]] if args.all else (args.cases or DEFAULT_CASES)

    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()

    grand_ok = grand_tot = 0
    for entry in manifest["cases"]:
        if entry["order_id"] not in wanted:
            continue
        for fname in (entry["files"] if args.variants else [entry["file"]]):
            print("== %s %s (%s)" % (entry["order_id"], entry["case"], fname))
            ok, tot, notes = check_case(engine, entry, fname, args.dump)
            grand_ok += ok
            grand_tot += tot
            print("   %d/%d fields read correctly" % (ok, tot))
            for n in notes:
                print("   MISS: %s" % n)
    print("TOTAL %d/%d" % (grand_ok, grand_tot))
    return 0 if grand_ok == grand_tot else 1


if __name__ == "__main__":
    sys.exit(main())
