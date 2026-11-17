"""
Unit and integration tests for Indian license plate normalization and syntax validation.
Verifies ML-A-001 regression contract, Indian statutory formats (Standard, BH, EV,
Commercial, Military, Diplomatic, Vintage, Temporary), HSRP IND stripping,
and positional OCR character confusion variants.
"""

import pytest
from research_track.track_a.src.plate_normalizer import (
    ALL_VALID_STATES,
    CURRENT_STATES,
    FORMER_STATES,
    NormalizedPlate,
    PlateNormalizer,
    is_valid_indian_plate,
    normalize_plate,
)


class TestEmptyAndWhitespaceHandlingMLA001:
    """Check ML-A-001 compliance for empty and whitespace OCR handling."""

    def test_empty_string_returns_unreadable(self):
        res = normalize_plate("")
        assert res.status == "UNREADABLE"
        assert "UNREADABLE" in res.status.upper()
        assert res.clean_text == ""
        assert str(res) == ""
        assert res.is_valid_format is False
        assert res.format_type == "UNREADABLE"

    def test_whitespace_string_returns_unreadable(self):
        res = normalize_plate("   ")
        assert res.status == "UNREADABLE"
        assert "UNREADABLE" in res.status.upper()
        assert res.clean_text == ""
        assert str(res) == ""
        assert res.is_valid_format is False

    def test_tabs_and_newlines_return_unreadable(self):
        res = normalize_plate("\t\n  \r\n")
        assert res.status == "UNREADABLE"
        assert res.clean_text == ""

    def test_none_input_returns_unreadable(self):
        res = normalize_plate(None)
        assert res.status == "UNREADABLE"
        assert res.clean_text == ""
        assert res.is_valid_format is False

    def test_punctuation_only_noise_returns_unreadable(self):
        res = normalize_plate("   ---   ...   :::   ")
        assert res.status == "UNREADABLE"
        assert res.clean_text == ""
        assert res.is_valid_format is False


class TestStandardIndianPlateFormats:
    """Verifies standard 10-character state format and district/series conventions."""

    @pytest.mark.parametrize("plate,expected_state,expected_dist,expected_series,expected_num", [
        ("CH01AB1234", "CH", "01", "AB", "1234"),
        ("PB65AZ9999", "PB", "65", "AZ", "9999"),
        ("DL01C1234", "DL", "01", "C", "1234"),
        ("HR26DK3456", "HR", "26", "DK", "3456"),
        ("HP12A1234", "HP", "12", "A", "1234"),
        ("MH12DE1428", "MH", "12", "DE", "1428"),
        ("KA011234", "KA", "01", "", "1234"),  # Karnataka blank series
        ("DL1C1234", "DL", "1", "C", "1234"),   # Delhi single-digit RTO
    ])
    def test_valid_standard_plates(self, plate, expected_state, expected_dist, expected_series, expected_num):
        res = normalize_plate(plate)
        assert res.status == "VALID"
        assert res.is_valid_format is True
        assert res.format_type == "STANDARD_INDIAN"
        assert res.state_code == expected_state
        assert res.district_code == expected_dist
        assert res.series_code == expected_series
        assert res.number_code == expected_num

    def test_all_current_states_recognized(self):
        for state in CURRENT_STATES:
            plate = f"{state}01AA1111"
            res = normalize_plate(plate)
            assert res.is_valid_format is True
            assert res.state_code == state

    def test_all_former_states_recognized_with_note(self):
        for state in FORMER_STATES:
            plate = f"{state}01AA1111"
            res = normalize_plate(plate)
            assert res.is_valid_format is True
            assert res.state_code == state
            assert any("Former state/UT code" in note for note in res.validation_notes)

    def test_invalid_standard_single_digit_rto_outside_delhi(self):
        # Only Delhi allows single-digit RTO
        res = normalize_plate("CH1AB1234")
        assert res.is_valid_format is False
        assert any("Single-digit RTO outside Delhi" in note for note in res.validation_notes)

    def test_invalid_number_all_zeros(self):
        res = normalize_plate("CH01AB0000")
        assert res.is_valid_format is False
        assert any("Registration number is 0000" in note for note in res.validation_notes)

    def test_series_with_i_or_o_rejected(self):
        # Letters I and O are excluded from Indian series
        res = normalize_plate("CH01AI1234")
        assert res.is_valid_format is False
        res_o = normalize_plate("PB65AO1234")
        assert res_o.is_valid_format is False


class TestBharatSeriesBHPlates:
    """Verifies Bharat Series (BH) formats (introduced 2021)."""

    @pytest.mark.parametrize("plate,expected_year,expected_num,expected_series", [
        ("22BH1234AA", "22", "1234", "AA"),
        ("21BH0001A", "21", "0001", "A"),
        ("23BH5678JK", "23", "5678", "JK"),
        ("24BH9999ZZ", "24", "9999", "ZZ"),
    ])
    def test_valid_bh_plates(self, plate, expected_year, expected_num, expected_series):
        res = normalize_plate(plate)
        assert res.status == "VALID"
        assert res.is_valid_format is True
        assert res.format_type == "BH_SERIES"
        assert res.state_code == "BH"
        assert res.district_code == expected_year
        assert res.number_code == expected_num
        assert res.series_code == expected_series

    def test_bh_plate_pre_2021_year_rejected(self):
        res = normalize_plate("19BH1234AA")
        assert res.is_valid_format is False

    def test_bh_plate_number_zeros_rejected(self):
        res = normalize_plate("22BH0000AA")
        assert res.is_valid_format is False


class TestHSRPINDStripping:
    """Verifies stripping of High Security Registration Plates (HSRP) IND prefix."""

    def test_hsrp_with_space_stripped(self):
        res = normalize_plate("IND DL01AB1234")
        assert res.clean_text == "DL01AB1234"
        assert res.is_valid_format is True
        assert any("HSRP" in note for note in res.validation_notes)

    def test_hsrp_without_space_stripped(self):
        res = normalize_plate("INDDL01AB1234")
        assert res.clean_text == "DL01AB1234"
        assert res.is_valid_format is True

    def test_hsrp_with_hyphens_stripped(self):
        res = normalize_plate("IND-CH-01-AB-1234")
        assert res.clean_text == "CH01AB1234"
        assert res.is_valid_format is True

    def test_hsrp_on_bh_series_stripped(self):
        res = normalize_plate("IND 22BH1234AA")
        assert res.clean_text == "22BH1234AA"
        assert res.is_valid_format is True
        assert res.format_type == "BH_SERIES"


class TestSpecializedVehicleFormats:
    """Verifies Electric Vehicles, Military, Diplomatic, Vintage, Temporary, and Commercial Trade."""

    def test_electric_vehicle_annotation(self):
        res = normalize_plate("DL01EV1234")
        assert res.is_valid_format is True
        assert any("Electric vehicle" in note for note in res.validation_notes)

    def test_delhi_commercial_vehicle_category(self):
        res_taxi = normalize_plate("DL01T1234")
        assert res_taxi.is_valid_format is True
        assert any("city taxi" in note for note in res_taxi.validation_notes)

        res_bus = normalize_plate("DL01P1234")
        assert res_bus.is_valid_format is True
        assert any("bus" in note for note in res_bus.validation_notes)

    def test_military_vehicle_with_upward_arrow(self):
        res_unicode = normalize_plate("↑21D123456A")
        assert res_unicode.clean_text == "21D123456A"
        assert res_unicode.is_valid_format is True
        assert res_unicode.format_type == "MILITARY"

        res_caret = normalize_plate("^21D123456A")
        assert res_caret.clean_text == "21D123456A"
        assert res_caret.is_valid_format is True
        assert res_caret.format_type == "MILITARY"

    def test_diplomatic_corps_plates(self):
        res_cd = normalize_plate("22CD1234")
        assert res_cd.is_valid_format is True
        assert res_cd.format_type == "DIPLOMATIC"

        res_cc = normalize_plate("19CC5678")
        assert res_cc.is_valid_format is True
        assert res_cc.format_type == "DIPLOMATIC"

        res_un = normalize_plate("77UN1234")
        assert res_un.is_valid_format is True
        assert res_un.format_type == "DIPLOMATIC"

    def test_vintage_plate_format(self):
        res = normalize_plate("DLVAAB1234")
        assert res.is_valid_format is True
        assert res.format_type == "VINTAGE"

    def test_temporary_plate_format(self):
        res = normalize_plate("T0421DL1234A")
        assert res.is_valid_format is True
        assert res.format_type == "TEMPORARY"

    def test_commercial_trade_certificate(self):
        res = normalize_plate("DL01ATC1234")
        assert res.is_valid_format is True
        assert res.format_type == "COMMERCIAL_TRADE"


class TestOCRCharacterAmbiguitiesAndVariants:
    """Verifies positional OCR character confusion variant generation."""

    def test_o_vs_0_in_district_code(self):
        # 'O' at district index 3 should suggest digit '0'
        res = normalize_plate("CHO1AB1234")
        assert res.is_valid_format is False
        variants = [v[0] for v in res.confusion_variants]
        assert "CH01AB1234" in variants

    def test_i_vs_1_in_numeric_block(self):
        # 'I' at number index 6 should suggest digit '1'
        res = normalize_plate("PB65AKI122")
        assert res.is_valid_format is False
        variants = [v[0] for v in res.confusion_variants]
        assert "PB65AK1122" in variants

    def test_z_vs_2_in_numeric_block(self):
        # 'Z' in numeric position should suggest digit '2'
        res = normalize_plate("DL01AA1Z34")
        assert res.is_valid_format is False
        variants = [v[0] for v in res.confusion_variants]
        assert "DL01AA1234" in variants

    def test_b_vs_8_in_numeric_block(self):
        # 'B' in numeric position should suggest digit '8'
        res = normalize_plate("CH01AC567B")
        assert res.is_valid_format is False
        variants = [v[0] for v in res.confusion_variants]
        assert "CH01AC5678" in variants

    def test_s_vs_5_in_bh_series_numeric_block(self):
        # 'S' in BH numeric position should suggest digit '5'
        res = normalize_plate("22BH34S6EF")
        assert res.is_valid_format is False
        variants = [v[0] for v in res.confusion_variants]
        assert "22BH3456EF" in variants

    def test_digit_in_state_prefix_suggests_letter(self):
        # Digit '0' at index 0 should suggest letter 'O'
        res = normalize_plate("0D01AB1234")
        variants = [v[0] for v in res.confusion_variants]
        assert any(v.startswith("OD") for v in variants)


class TestIdempotenceAndNonDestructiveness:
    """Verifies non-destructive audit invariants."""

    def test_idempotence(self):
        raw = "  pb-65-ak-1122  "
        first = normalize_plate(raw)
        second = normalize_plate(first.clean_text)
        assert first.clean_text == second.clean_text
        assert first.clean_text == "PB65AK1122"
        assert first.raw_text == raw

    def test_raw_text_immutable(self):
        raw = "  CH-01  AB-1234  "
        res = normalize_plate(raw)
        assert res.raw_text == raw
        assert res.clean_text == "CH01AB1234"
        assert str(res) == "CH01AB1234"

    def test_is_valid_indian_plate_helper(self):
        assert is_valid_indian_plate("CH01AB1234") is True
        assert is_valid_indian_plate("22BH1234AA") is True
        assert is_valid_indian_plate("INVALID123") is False
        assert is_valid_indian_plate("   ") is False
        assert is_valid_indian_plate(None) is False
