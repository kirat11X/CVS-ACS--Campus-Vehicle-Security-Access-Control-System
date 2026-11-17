"""
Unit Test Suite for Institutional Identifier Schema Validation.

Statutory Rules Tested:
1. STUDENT: Exactly 8 numeric digits (e.g., '24103042').
2. FACULTY: 'F' followed by 7 numeric digits (e.g., 'F1234567').
3. RESIDENT: 'R' followed by 4-digit house number (e.g., 'R1042').
4. STAFF: Institutional employee code (e.g., 'STF-EST-022' or 'S1234567').
"""

import pytest
from pydantic import ValidationError
from backend.app.models.enums import PersonType, ResidenceType
from backend.app.schemas.owner import OwnerCreate
from backend.app.schemas.movement import NewOwnerForLink
from backend.app.services.identifier_validator import validate_and_normalize_identifier


class TestIdentifierValidator:
    def test_student_id_valid(self):
        assert validate_and_normalize_identifier("24103042", PersonType.STUDENT) == "24103042"
        assert validate_and_normalize_identifier("12345678", "STUDENT") == "12345678"
        assert validate_and_normalize_identifier(" 24103999 ", PersonType.STUDENT) == "24103999"

    @pytest.mark.parametrize("invalid_sid", ["2410304", "241030429", "2410304A", "STUDENT-1", "abcdefgh"])
    def test_student_id_invalid(self, invalid_sid):
        with pytest.raises(ValueError, match="Student ID must be exactly 8 numeric digits"):
            validate_and_normalize_identifier(invalid_sid, PersonType.STUDENT)

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="Institutional identifier cannot be empty"):
            validate_and_normalize_identifier("", PersonType.STUDENT)

    def test_faculty_id_valid(self):
        assert validate_and_normalize_identifier("F1234567", PersonType.FACULTY) == "F1234567"
        # Case insensitive input normalized to uppercase
        assert validate_and_normalize_identifier("f7654321", "FACULTY") == "F7654321"

    @pytest.mark.parametrize("invalid_fid", ["F123456", "F12345678", "FAC-1234567", "12345678", "G1234567"])
    def test_faculty_id_invalid(self, invalid_fid):
        with pytest.raises(ValueError, match="Faculty ID must start with 'F' followed by 7 digits"):
            validate_and_normalize_identifier(invalid_fid, PersonType.FACULTY)

    def test_resident_id_valid(self):
        assert validate_and_normalize_identifier("R1042", PersonType.RESIDENT) == "R1042"
        assert validate_and_normalize_identifier("r0105", "RESIDENT") == "R0105"

    @pytest.mark.parametrize("invalid_rid", ["R104", "R10425", "1042", "H1042", "RABCD"])
    def test_resident_id_invalid(self, invalid_rid):
        with pytest.raises(ValueError, match="Residence ID must start with 'R' followed by a 4-digit house number"):
            validate_and_normalize_identifier(invalid_rid, PersonType.RESIDENT)

    def test_staff_id_valid(self):
        assert validate_and_normalize_identifier("STF-EST-022", PersonType.STAFF) == "STF-EST-022"
        assert validate_and_normalize_identifier("S1234567", PersonType.STAFF) == "S1234567"


class TestOwnerCreateSchema:
    def test_owner_create_student_success(self):
        owner = OwnerCreate(
            identifier="24103042",
            full_name="Kirat Singh",
            person_type=PersonType.STUDENT,
            residence_type=ResidenceType.HOSTELLER,
            residence="BH-4, Room 312",
        )
        assert owner.identifier == "24103042"
        assert owner.person_type == PersonType.STUDENT

    def test_owner_create_faculty_success(self):
        owner = OwnerCreate(
            identifier="f1029384",
            full_name="Dr. Sharma",
            person_type=PersonType.FACULTY,
            department="Computer Science",
        )
        assert owner.identifier == "F1029384"
        assert owner.person_type == PersonType.FACULTY

    def test_owner_create_resident_auto_residence(self):
        owner = OwnerCreate(
            identifier="r2048",
            full_name="Col. Verma",
            person_type=PersonType.RESIDENT,
        )
        assert owner.identifier == "R2048"
        assert owner.residence == "House 2048"

    def test_owner_create_invalid_sid_raises(self):
        with pytest.raises(ValidationError) as exc:
            OwnerCreate(
                identifier="STUDENT-INVALID",
                full_name="Test Student",
                person_type=PersonType.STUDENT,
            )
        assert "Student ID must be exactly 8 numeric digits" in str(exc.value)


class TestNewOwnerForLinkSchema:
    def test_link_new_owner_student_success(self):
        link_owner = NewOwnerForLink(
            person_type=PersonType.STUDENT,
            identifier="24103042",
            full_name="Kirat Singh",
            residence="BH-1",
        )
        assert link_owner.identifier == "24103042"

    def test_link_new_owner_invalid_faculty_raises(self):
        with pytest.raises(ValidationError) as exc:
            NewOwnerForLink(
                person_type=PersonType.FACULTY,
                identifier="FAC-999",
                full_name="Dr. Test",
            )
        assert "Faculty ID must start with 'F' followed by 7 digits" in str(exc.value)
