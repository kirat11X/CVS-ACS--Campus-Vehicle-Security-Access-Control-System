"""Indian registration plates: classify a read as one of the recognised formats, or say exactly why it is not one.

    state (2 letters) + RTO/zone (2 digits) + series (letters, no I or O) + number (4 digits)      MH 12 AB 1234

plus the exceptions: Delhi (RTO without a leading zero, first series letter is the vehicle category), Karnataka
(blank series), the Bharat (BH), vintage (VA), armed-forces, diplomatic, temporary and trade formats, and the state
codes that were retired (UA, OR, DN, TS). Sources, disagreements between them and the known gaps are in
research_track/hitl_anpr/INDIAN_PLATE_FORMATS.md; the rules below cite the section there.

A read is never rewritten. `suggest_repairs` lists O/0, I/1, B/8, S/5 swaps that would turn an invalid read into a
valid one, for a reviewer to look at (the same pairs and the same never-applied rule as plates.py).

This module is separate from plates.py on purpose: plates.py keeps the research pipeline's original strict pattern
(its tests pin it); the review/labelling scripts use this one.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from datetime import date

from anpr_hitl.plates import CONFUSION_PAIRS, normalize_plate

# --- state / UT codes (INDIAN_PLATE_FORMATS.md section 2) ---------------------------------------------------------------
CURRENT_STATES = {
    "AN": "Andaman and Nicobar Islands", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam",
    "BR": "Bihar", "CG": "Chhattisgarh", "CH": "Chandigarh", "DD": "Dadra and Nagar Haveli and Daman and Diu",
    "DL": "Delhi", "GA": "Goa", "GJ": "Gujarat", "HP": "Himachal Pradesh", "HR": "Haryana", "JH": "Jharkhand",
    "JK": "Jammu and Kashmir", "KA": "Karnataka", "KL": "Kerala", "LA": "Ladakh", "LD": "Lakshadweep",
    "MH": "Maharashtra", "ML": "Meghalaya", "MN": "Manipur", "MP": "Madhya Pradesh", "MZ": "Mizoram",
    "NL": "Nagaland", "OD": "Odisha", "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan", "SK": "Sikkim",
    "TG": "Telangana", "TN": "Tamil Nadu", "TR": "Tripura", "UK": "Uttarakhand", "UP": "Uttar Pradesh",
    "WB": "West Bengal",
}
# Retired codes stay valid on vehicles registered while they were current: code -> (name, last issued, successor).
FORMER_STATES = {
    "UA": ("Uttaranchal", "2007-10-31", "UK"),
    "OR": ("Orissa", "2012-08-30", "OD"),
    "DN": ("Dadra and Nagar Haveli", "2020-01-25", "DD"),
    "TS": ("Telangana", "2024-03-14", "TG"),
}

# --- exceptions ---------------------------------------------------------------------------------------------------------
EXCLUDED_SERIES_LETTERS = frozenset("IO")   # never used in series letters (common practice; no rule text found)
BLANK_SERIES_STATES = frozenset({"KA"})     # Karnataka issues some series with no letters; elsewhere a missing series = a bad read
BH_FIRST_YEAR = 21                          # Bharat series started 15 Sep 2021
TEMPORARY_FIRST_YEAR = 21                   # the "T MMYY SS NNNN L" temporary format came with the 31 Mar 2021 notification
DELHI_CATEGORIES = {                        # first series letter of a Delhi plate = vehicle category
    "A": "ambulance", "B": "mini bus", "C": "car", "E": "other commercial", "F": "private (number on demand)",
    "G": "truck", "K": "school vehicle", "L": "truck", "M": "other commercial", "N": "self-drive vehicle",
    "P": "bus", "Q": "commercial three-wheeler", "R": "autorickshaw / radio taxi", "S": "two-wheeler",
    "T": "city taxi", "U": "other commercial", "V": "other commercial", "W": "other commercial",
    "Y": "private taxi", "Z": "other commercial",
}
MILITARY_CLASSES = {                        # sources disagree on the full list, so an unlisted letter is only a note
    "A": "two-wheeler", "B": "light motor vehicle", "C": "truck", "D": "heavy truck", "E": "high-mobility vehicle",
    "F": "light specialist vehicle", "G": "trailer", "H": "truck with material handling", "J": "snow removal",
    "K": "ambulance", "P": "support vehicle (bus, fire truck, tanker ...)", "Q": "construction vehicle",
    "R": "customised vehicle", "X": "combat vehicle",
}
DIPLOMATIC_TYPES = {"CD": "embassy", "CC": "consulate", "UN": "United Nations", "IOD": "international organisation"}

_BH = re.compile(r"^(\d{2})BH(\d{4})([A-Z]{1,2})$")
_TEMPORARY = re.compile(r"^T(\d{2})(\d{2})([A-Z]{2})(\d{4})([A-Z]{1,2})$")
_DIPLOMATIC = re.compile(r"^([1-9]\d{0,2})(CD|CC|UN|IOD)([1-9]\d{0,3}[A-Z]?)$")
_MILITARY = re.compile(r"^(\d{2})([A-Z])(\d{6})([A-Z])$")
_VINTAGE = re.compile(r"^([A-Z]{2})VA([A-Z]{2})(\d{4})$")
_TRADE = re.compile(r"^([A-Z]{2})(\d{2})([A-J])(\d{4})TC(\d{1,4})$")
_STANDARD = re.compile(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{4})$")
_TRADE_OLD = re.compile(r"^([A-Z]{2})(\d{1,2})TC(\d{2,6})$")
_LEGACY = re.compile(r"^[A-Z]{3}\d{1,4}$")


@dataclass(frozen=True)
class PlateClass:
    text: str                       # the read, normalised to A-Z0-9
    kind: str | None                # standard, delhi, bh, vintage, military, diplomatic, temporary, trade, trade_legacy
    valid: bool                     # a recognised Indian format with nothing wrong
    state: str = ""
    state_status: str = ""          # "current" or "former"
    rto: str = ""
    series: str = ""
    number: str = ""
    notes: tuple[str, ...] = ()     # information about a valid plate (Delhi category, retired state code, ...)
    reasons: tuple[str, ...] = ()   # why it is not valid


def _state(code: str) -> tuple[str, list[str], list[str]]:
    if code in CURRENT_STATES:
        return "current", [], []
    if code in FORMER_STATES:
        _, until, successor = FORMER_STATES[code]
        return "former", [f"former_state_code:{code}_now_{successor}_until_{until}"], []
    return "", [], ["unknown_state"]


def _year_ok(yy: int, first: int, today: date) -> bool:
    return first <= yy <= today.year % 100


def classify_plate(raw: str | None, today: date | None = None) -> PlateClass:
    """Classify a read. Never raises, never rewrites the text."""
    today = today or date.today()
    text = normalize_plate(raw)
    if not text:
        return PlateClass("", None, False, reasons=("empty",))

    def done(kind, state="", status="", rto="", series="", number="", notes=(), reasons=()):
        return PlateClass(text, kind, not reasons, state, status, rto, series, number, tuple(notes), tuple(reasons))

    if m := _BH.match(text):
        yy, number, series = m.groups()
        reasons = []
        if not _year_ok(int(yy), BH_FIRST_YEAR, today):
            reasons.append("bh_year_out_of_range")
        if EXCLUDED_SERIES_LETTERS & set(series):
            reasons.append("series_contains_I_or_O")
        return done("bh", series=series, number=number, notes=[f"registered_20{yy}"], reasons=reasons)

    if m := _TEMPORARY.match(text):
        month, yy, state, number, series = m.groups()
        status, notes, reasons = _state(state)
        if not 1 <= int(month) <= 12:
            reasons.append("temporary_month_invalid")
        if not _year_ok(int(yy), TEMPORARY_FIRST_YEAR, today):
            reasons.append("temporary_year_out_of_range")
        if EXCLUDED_SERIES_LETTERS & set(series):
            reasons.append("series_contains_I_or_O")
        return done("temporary", state, status, series=series, number=number, notes=notes, reasons=reasons)

    if m := _DIPLOMATIC.match(text):
        mission, kind, number = m.groups()
        return done("diplomatic", rto=mission, series=kind, number=number, notes=[f"mission_{DIPLOMATIC_TYPES[kind]}"])

    if m := _MILITARY.match(text):
        yy, cls, serial, check = m.groups()
        notes = [f"procured_20{yy}", f"class_{MILITARY_CLASSES[cls]}" if cls in MILITARY_CLASSES else "class_unlisted"]
        return done("military", series=cls + check, number=serial, notes=notes)

    if m := _VINTAGE.match(text):
        state, series, number = m.groups()
        status, notes, reasons = _state(state)
        if EXCLUDED_SERIES_LETTERS & set(series):
            reasons.append("series_contains_I_or_O")
        return done("vintage", state, status, series=series, number=number, notes=notes, reasons=reasons)

    if m := _TRADE.match(text):
        state, rto, category, holder, vehicle = m.groups()
        status, notes, reasons = _state(state)
        if int(rto) == 0:
            reasons.append("rto_zero")
        return done("trade", state, status, rto, category, holder + vehicle, notes, reasons)

    if m := _STANDARD.match(text):
        state, rto, series, number = m.groups()
        status, notes, reasons = _state(state)
        delhi = state == "DL"
        if int(rto) == 0:
            reasons.append("rto_zero")
        elif len(rto) == 1:
            if delhi:
                notes.append("delhi_unpadded_rto")
            else:
                reasons.append("rto_not_two_digits")
        if not series:
            if state in BLANK_SERIES_STATES:
                notes.append("blank_series")
            else:
                reasons.append("no_series_letters")
        elif EXCLUDED_SERIES_LETTERS & set(series):
            reasons.append("series_contains_I_or_O")
        if number == "0000":
            reasons.append("number_zero")
        if delhi and series:
            category = DELHI_CATEGORIES.get(series[0])
            notes.append(f"delhi_category_{category}" if category else "delhi_category_unlisted")
        return done("delhi" if delhi else "standard", state, status, rto, series, number, notes, reasons)

    if m := _TRADE_OLD.match(text):
        state, rto, numbers = m.groups()
        status, notes, reasons = _state(state)
        if int(rto) == 0:
            reasons.append("rto_zero")
        return done("trade_legacy", state, status, rto, "TC", numbers, notes, reasons)

    if _LEGACY.match(text):
        return done(None, reasons=["legacy_1940_1989_not_validated"])
    return done(None, reasons=["pattern_mismatch"])


def is_indian_plate(raw: str | None, today: date | None = None) -> bool:
    return classify_plate(raw, today).valid


MAX_REPAIR_POSITIONS = 8  # cap on the swap search (2^8 variants)


def suggest_repairs(raw: str | None, today: date | None = None) -> list[str]:
    """O/0, I/1, B/8, S/5 swaps that make an invalid read a valid plate, fewest swaps first. Suggestions only."""
    text = normalize_plate(raw)
    if not text or classify_plate(text, today).valid:
        return []
    positions = [i for i, ch in enumerate(text) if ch in CONFUSION_PAIRS][:MAX_REPAIR_POSITIONS]
    found: set[tuple[int, str]] = set()
    for k in range(1, len(positions) + 1):
        for subset in itertools.combinations(positions, k):
            chars = list(text)
            for i in subset:
                chars[i] = CONFUSION_PAIRS[chars[i]]
            variant = "".join(chars)
            if classify_plate(variant, today).valid:
                found.add((k, variant))
    return [v for _, v in sorted(found)]
