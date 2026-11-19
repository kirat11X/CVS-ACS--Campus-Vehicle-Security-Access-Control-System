import re
from typing import Optional

# Comprehensive list of 36 Current States/UTs + 4 Former States (valid on older vehicles)
CURRENT_STATES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "GA", "GJ", "HP", "HR", "JH",
    "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY",
    "RJ", "SK", "TG", "TN", "TR", "UK", "UP", "WB"
}
FORMER_STATES = {"UA", "OR", "DN", "TS"}
ALL_VALID_STATES = CURRENT_STATES | FORMER_STATES

def normalize_plate(plate: str) -> str:
    """
    Normalizes license plate strings to canonical uppercase alphanumeric characters.
    Examples:
        'PB65 AB 1234'  -> 'PB65AB1234'
        'pb65-ab-1234'  -> 'PB65AB1234'
        'PB 65AB 1234'  -> 'PB65AB1234'
        'DL-01-AB-1234' -> 'DL01AB1234'
    """
    if not plate:
        return ""
    # Remove all non-alphanumeric characters and uppercase
    return re.sub(r"[^A-Za-z0-9]", "", plate).strip().upper()

def format_plate_display(normalized_plate: str) -> str:
    """
    Formats an Indian registration plate for readability according to national standards.
    Examples:
        'PB65AB1234'   -> 'PB 65 AB 1234'
        'DL3CAB1234'   -> 'DL 3 CAB 1234'
        '22BH1234AA'   -> '22 BH 1234 AA'
        'KA011234'     -> 'KA 01 1234'
        'MH12ABC1234'  -> 'MH 12 ABC 1234'
        'CH01A0001'    -> 'CH 01 A 0001'
    """
    if not normalized_plate:
        return ""
    p = normalize_plate(normalized_plate)

    # 1. Bharat Series (BH): YY BH #### XX (e.g. 22 BH 1234 AA)
    m_bh = re.match(r"^([0-9]{2})BH([0-9]{4})([A-Z]{1,2})$", p)
    if m_bh:
        return f"{m_bh.group(1)} BH {m_bh.group(2)} {m_bh.group(3)}"

    # 2. Vintage: SS VA XX #### (e.g. MH VA AB 0123)
    m_va = re.match(r"^([A-Z]{2})VA([A-Z]{2})([0-9]{4})$", p)
    if m_va:
        return f"{m_va.group(1)} VA {m_va.group(2)} {m_va.group(3)}"

    # 3. Standard / Delhi / Karnataka format:
    # State (2 letters) + RTO (1-2 digits) + Series (0-3 letters) + Number (4 digits)
    m_std = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$", p)
    if m_std:
        state, rto, series, number = m_std.groups()
        if series:
            return f"{state} {rto} {series} {number}"
        return f"{state} {rto} {number}"

    # 4. Diplomatic: NNN (CD|CC|UN|IOD) NNNN
    m_dip = re.match(r"^([0-9]{1,3})(CD|CC|UN|IOD)([0-9]{1,4}[A-Z]?)$", p)
    if m_dip:
        return f"{m_dip.group(1)} {m_dip.group(2)} {m_dip.group(3)}"

    return p

def is_valid_indian_plate(normalized_plate: str) -> bool:
    """
    Validates whether a normalized plate strictly follows statutory Indian plate formats.
    """
    if not normalized_plate:
        return False
    p = normalize_plate(normalized_plate)
    
    # Bharat Series: YY BH #### XX (year >= 21, no I or O in series)
    m_bh = re.match(r"^([0-9]{2})BH([0-9]{4})([A-Z]{1,2})$", p)
    if m_bh:
        yy, num, series = m_bh.groups()
        if int(yy) >= 21 and not any(c in series for c in "IO") and num != "0000":
            return True

    # Standard Format: State + RTO + Series (no I/O) + 4 digits (not 0000)
    m_std = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$", p)
    if m_std:
        state, rto, series, num = m_std.groups()
        if state not in ALL_VALID_STATES:
            return False
        if int(rto) == 0:
            return False
        # Outside Delhi, RTO must be 2 digits
        if len(rto) == 1 and state != "DL":
            return False
        # Series must not have I or O
        if any(c in series for c in "IO"):
            return False
        # Outside Karnataka, series cannot be blank
        if not series and state != "KA":
            return False
        if num == "0000":
            return False
        return True

    # Vintage
    m_va = re.match(r"^([A-Z]{2})VA([A-Z]{2})([0-9]{4})$", p)
    if m_va:
        state, series, num = m_va.groups()
        if state in ALL_VALID_STATES and not any(c in series for c in "IO") and num != "0000":
            return True

    # Diplomatic
    if re.match(r"^[0-9]{1,3}(CD|CC|UN|IOD)[0-9]{1,4}[A-Z]?$", p):
        return True

    # Military: YY [A-Z] 6-digits [A-Z]
    if re.match(r"^[0-9]{2}[A-Z][0-9]{6}[A-Z]$", p):
        return True

    return False


EXPANDED_DIGIT_TO_LETTER: dict[str, list[str]] = {
    "0": ["O", "D"],
    "1": ["I", "L"],
    "2": ["Z"],
    "3": ["E", "J"],
    "4": ["A"],
    "5": ["S"],
    "6": ["G"],
    "7": ["T"],
    "8": ["B"],
    "9": [],
}

EXPANDED_LETTER_TO_DIGIT: dict[str, list[str]] = {
    "O": ["0"],
    "D": ["0"],
    "Q": ["0"],
    "I": ["1"],
    "L": ["1"],
    "Z": ["2"],
    "E": ["3"],
    "J": ["3"],
    "A": ["4"],
    "S": ["5"],
    "G": ["6"],
    "T": ["7"],
    "B": ["8"],
}

# Legacy 1-to-1 confusion pairs kept for backward compatibility
CONFUSION_PAIRS: dict[str, str] = {
    "O": "0", "0": "O",
    "I": "1", "1": "I",
    "B": "8", "8": "B",
    "S": "5", "5": "S",
    "Z": "2", "2": "Z",
    "D": "0",
    "A": "4", "4": "A",
    "G": "6", "6": "G",
    "T": "7", "7": "T",
}


def _get_letter_candidates(ch: str) -> list[tuple[str, int]]:
    """Returns candidate letters for a letter slot: (char, swap_penalty)."""
    if ch.isalpha():
        return [(ch.upper(), 0)]
    alts = EXPANDED_DIGIT_TO_LETTER.get(ch, [])
    return [(alt, 1) for alt in alts]


def _get_digit_candidates(ch: str) -> list[tuple[str, int]]:
    """Returns candidate digits for a digit slot: (char, swap_penalty)."""
    if ch.isdigit():
        return [(ch, 0)]
    alts = EXPANDED_LETTER_TO_DIGIT.get(ch.upper(), [])
    return [(alt, 1) for alt in alts]


def suggest_repairs(raw: str | None) -> list[str]:
    """
    Evaluates positional syntax-constrained repairs to turn an invalid OCR read
    into a valid statutory Indian plate (Standard State or Bharat Series).
    Returns valid repaired plate candidates, fewest swaps first.
    """
    text = normalize_plate(raw)
    if not text or is_valid_indian_plate(text):
        return []

    import itertools

    length = len(text)
    found: set[tuple[int, str]] = set()

    # 1. Bharat Series Repair: YY BH #### XX (indices 0-1 digits, 2-3 BH, 4-7 digits, 8-9 letters)
    if 9 <= length <= 10:
        if (text[2] in "B80" and text[3] in "H4") or text[2:4] in {"BH", "8H", "B4", "84", "0H", "OH"}:
            y0_cands = _get_digit_candidates(text[0])
            y1_cands = _get_digit_candidates(text[1])
            b_cost = 0 if text[2] == "B" else 1
            h_cost = 0 if text[3] == "H" else 1

            n_cands = [_get_digit_candidates(text[i]) for i in range(4, 8)]
            s_cands = [_get_letter_candidates(text[i]) for i in range(8, length)]

            for y0, c_y0 in y0_cands:
                for y1, c_y1 in y1_cands:
                    yy = y0 + y1
                    if int(yy) < 21:
                        continue
                    for n_prod in itertools.product(*n_cands):
                        num_str = "".join(p[0] for p in n_prod)
                        c_num = sum(p[1] for p in n_prod)
                        if num_str == "0000":
                            continue
                        for s_prod in itertools.product(*s_cands):
                            ser_str = "".join(p[0] for p in s_prod)
                            c_ser = sum(p[1] for p in s_prod)
                            if any(c in ser_str for c in "IO"):
                                continue
                            cand = f"{yy}BH{num_str}{ser_str}"
                            if is_valid_indian_plate(cand):
                                total_c = c_y0 + c_y1 + b_cost + h_cost + c_num + c_ser
                                found.add((total_c, cand))

    # 2. Standard State Format: SS DD [L{1,3}] NNNN
    if 8 <= length <= 11:
        tail_cands = [_get_digit_candidates(text[i]) for i in range(length - 4, length)]
        c0_cands = _get_letter_candidates(text[0])
        c1_cands = _get_letter_candidates(text[1])

        state_cands = []
        for c0, cost0 in c0_cands:
            for c1, cost1 in c1_cands:
                st = c0 + c1
                if st in ALL_VALID_STATES:
                    state_cands.append((st, cost0 + cost1))

        m_len = length - 6
        splits = []
        # Standard: 2 digits RTO, middle letters (0-3)
        if m_len >= 0 and (m_len - 2) <= 3 and (m_len - 2) >= 0:
            splits.append((2, m_len - 2))
        # Delhi: 1 digit RTO, middle letters (1-3)
        if m_len >= 1 and (m_len - 1) <= 3 and (m_len - 1) >= 1:
            splits.append((1, m_len - 1))

        for rto_len, ser_len in splits:
            for st, st_cost in state_cands:
                if rto_len == 1 and st != "DL":
                    continue
                if ser_len == 0 and st != "KA":
                    continue

                rto_cands = [_get_digit_candidates(text[2 + i]) for i in range(rto_len)]
                ser_cands = [_get_letter_candidates(text[2 + rto_len + i]) for i in range(ser_len)]

                for rto_prod in itertools.product(*rto_cands):
                    rto_str = "".join(p[0] for p in rto_prod)
                    rto_cost = sum(p[1] for p in rto_prod)
                    if int(rto_str) == 0:
                        continue
                    for ser_prod in (itertools.product(*ser_cands) if ser_len > 0 else [()]):
                        ser_str = "".join(p[0] for p in ser_prod)
                        ser_cost = sum(p[1] for p in ser_prod)
                        if any(c in ser_str for c in "IO"):
                            continue
                        for tail_prod in itertools.product(*tail_cands):
                            tail_str = "".join(p[0] for p in tail_prod)
                            tail_cost = sum(p[1] for p in tail_prod)
                            if tail_str == "0000":
                                continue
                            cand = f"{st}{rto_str}{ser_str}{tail_str}"
                            if is_valid_indian_plate(cand):
                                total_c = st_cost + rto_cost + ser_cost + tail_cost
                                found.add((total_c, cand))

    return [v for _, v in sorted(found)]


def repair_plate_positional(raw: str | None) -> Optional[str]:
    """
    Positional syntax-constrained Indian plate repair.
    - If raw is already a valid Indian plate, preserves it exactly (e.g. '22BH1234AA').
    - If raw has OCR letter/digit confusions, repairs using statutory positional constraints
      (e.g. 'P810A81234' -> 'PB10AB1234', '0L01AB1234' -> 'DL01AB1234').
    - Returns None if the plate cannot be repaired to a valid statutory Indian format.
    """
    text = normalize_plate(raw)
    if not text:
        return None
    if is_valid_indian_plate(text):
        return text
    candidates = suggest_repairs(text)
    return candidates[0] if candidates else None

