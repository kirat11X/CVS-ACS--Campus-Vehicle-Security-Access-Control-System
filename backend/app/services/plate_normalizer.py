import re

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
    Formats a 9-10 character Indian registration plate for readability.
    Example:
        'PB65AB1234' -> 'PB 65 AB 1234'
        'DL1LAB5678' -> 'DL 1L AB 5678'
    """
    p = normalize_plate(normalized_plate)
    # Standard format: 2 state letters + 1-2 district digits/letters + 1-2 series letters + 4 digits
    match = re.match(r"^([A-Z]{2})([0-9]{1,2}[A-Z]{0,2})([A-Z]{1,2})([0-9]{4})$", p)
    if match:
        return f"{match.group(1)} {match.group(2)} {match.group(3)} {match.group(4)}"
    return p
