import re

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


CONFUSION_PAIRS: dict[str, str] = {
    "O": "0", "0": "O",
    "I": "1", "1": "I",
    "B": "8", "8": "B",
    "S": "5", "5": "S",
    "Z": "2", "2": "Z",
}


def suggest_repairs(raw: str | None) -> list[str]:
    """
    Evaluates O/0, I/1, B/8, S/5, Z/2 swaps to turn an invalid OCR read into a valid Indian plate.
    Returns valid repaired plate candidates, fewest swaps first.
    """
    text = normalize_plate(raw)
    if not text or is_valid_indian_plate(text):
        return []
    import itertools

    positions = [i for i, ch in enumerate(text) if ch in CONFUSION_PAIRS][:8]
    found: set[tuple[int, str]] = set()
    for k in range(1, min(4, len(positions) + 1)):
        for subset in itertools.combinations(positions, k):
            chars = list(text)
            for i in subset:
                chars[i] = CONFUSION_PAIRS[chars[i]]
            candidate = "".join(chars)
            if is_valid_indian_plate(candidate):
                found.add((k, candidate))
    return [v for _, v in sorted(found)]

