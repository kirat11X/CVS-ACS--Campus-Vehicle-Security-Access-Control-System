"""
Institutional Identifier Validation and Normalization Service.

Enforces statutory campus ID formatting rules:
1. STUDENT: Exactly 8 numeric digits (e.g. '24103042').
2. FACULTY: Starts with 'F' followed by 7 numeric digits (e.g. 'F1234567').
3. RESIDENT: Starts with 'R' followed by 4-digit house number (e.g. 'R1042').
4. STAFF: Institutional employee code (e.g. 'STF-EST-022' or 'S1234567').
"""

import re
from typing import Union
from backend.app.models.enums import PersonType

STUDENT_ID_REGEX = re.compile(r"^\d{8}$")
FACULTY_ID_REGEX = re.compile(r"^F\d{7}$", re.IGNORECASE)
RESIDENT_ID_REGEX = re.compile(r"^R\d{4}$", re.IGNORECASE)
STAFF_ID_REGEX = re.compile(r"^(?:STF-[A-Z0-9_-]+|S\d{7}|[A-Z0-9_-]{3,30})$", re.IGNORECASE)


def validate_and_normalize_identifier(identifier: str, person_type: Union[PersonType, str]) -> str:
    """
    Validates and normalizes institutional identifiers according to campus statutory schema.
    Raises ValueError with descriptive guidance if formatting requirements are violated.
    """
    clean = (identifier or "").strip()
    if not clean:
        raise ValueError("Institutional identifier cannot be empty.")

    p_type = person_type.value if hasattr(person_type, "value") else str(person_type).upper()

    if p_type == "STUDENT":
        if not STUDENT_ID_REGEX.fullmatch(clean):
            raise ValueError(
                f"Invalid Student ID '{clean}'. Student ID must be exactly 8 numeric digits (e.g., 24103042)."
            )
        return clean

    elif p_type == "FACULTY":
        if not FACULTY_ID_REGEX.fullmatch(clean):
            raise ValueError(
                f"Invalid Faculty ID '{clean}'. Faculty ID must start with 'F' followed by 7 digits (e.g., F1234567)."
            )
        return clean.upper()

    elif p_type == "RESIDENT":
        if not RESIDENT_ID_REGEX.fullmatch(clean):
            raise ValueError(
                f"Invalid Residence ID '{clean}'. Residence ID must start with 'R' followed by a 4-digit house number (e.g., R1042)."
            )
        return clean.upper()

    elif p_type == "STAFF":
        if not STAFF_ID_REGEX.fullmatch(clean):
            raise ValueError(
                f"Invalid Staff ID '{clean}'. Staff ID must be a valid institutional code (e.g., STF-001 or S1234567)."
            )
        return clean.upper()

    return clean
