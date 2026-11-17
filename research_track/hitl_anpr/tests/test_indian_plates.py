"""Indian plate formats and exceptions (research_track/hitl_anpr/INDIAN_PLATE_FORMATS.md)."""

from datetime import date

import pytest

from anpr_hitl.indian_plates import (
    CURRENT_STATES,
    FORMER_STATES,
    classify_plate,
    is_indian_plate,
    suggest_repairs,
)
from anpr_hitl.plates import STATE_CODES

TODAY = date(2026, 10, 16)


def c(text):
    return classify_plate(text, TODAY)


@pytest.mark.parametrize("raw,kind", [
    ("MH 12 AB 1234", "standard"), ("PB65AS1234", "standard"), ("CH 01 A 0001", "standard"),
    ("DL 01 CAB 1234", "delhi"), ("TN 58 N 4006", "standard"), ("AP 39 Z 1234", "standard"),
    ("22 BH 1234 AB", "bh"), ("23BH0001A", "bh"), ("21 BH 0000 AA", "bh"),
    ("MH VA AB 0123", "vintage"),
    ("T 1123 LA 0123 A", "temporary"), ("T0124AN0123AB", "temporary"),
    ("LA 01 C 0001 TC 0001", "trade"), ("UP 16 TC 020007", "trade_legacy"),
    ("01Z012345A", "military"), ("22B123456C", "military"),
    ("12 CD 3456", "diplomatic"), ("11 CD 1A", "diplomatic"), ("31 UN 12", "diplomatic"), ("199 IOD 99", "diplomatic"),
])
def test_recognised_formats(raw, kind):
    plate = c(raw)
    assert plate.valid, plate.reasons
    assert plate.kind == kind


def test_delhi_has_no_leading_zero_and_a_category_letter():
    plate = c("DL 3C AB 1234")
    assert (plate.valid, plate.kind, plate.state, plate.rto, plate.series, plate.number) == (True, "delhi", "DL", "3", "CAB", "1234")
    assert "delhi_unpadded_rto" in plate.notes and "delhi_category_car" in plate.notes
    assert c("DL1SCA0001").notes[1] == "delhi_category_two-wheeler"
    assert c("DL 10 CA 1234").valid and "delhi_unpadded_rto" not in c("DL 10 CA 1234").notes


def test_only_delhi_may_skip_the_leading_zero():
    plate = c("MH 1 AB 1234")
    assert not plate.valid and plate.reasons == ("rto_not_two_digits",)


def test_blank_series_is_karnataka_only():
    assert c("KA 01 1234").valid and "blank_series" in c("KA 01 1234").notes
    plate = c("MH 12 1234")  # what a read that lost its letters looks like
    assert not plate.valid and plate.reasons == ("no_series_letters",)


@pytest.mark.parametrize("raw,reason", [
    ("MH 12 AB 123", "pattern_mismatch"),
    ("MH 12 OA 1234", "series_contains_I_or_O"),
    ("MH 12 IA 1234", "series_contains_I_or_O"),
    ("XX 12 AB 1234", "unknown_state"),
    ("MH 00 AB 1234", "rto_zero"),
    ("DL 0 CA 1234", "rto_zero"),
    ("MH 12 AB 0000", "number_zero"),
    ("MH 12 ABCD 1234", "pattern_mismatch"),
    ("22 BH 1234 IO", "series_contains_I_or_O"),
    ("20 BH 1234 AA", "bh_year_out_of_range"),   # before the series existed
    ("27 BH 1234 AA", "bh_year_out_of_range"),   # in the future
    ("T 1323 LA 0123 A", "temporary_month_invalid"),
    ("T 1120 LA 0123 A", "temporary_year_out_of_range"),
    ("ABC 1234", "legacy_1940_1989_not_validated"),
    ("", "empty"),
    ("120M8882", "pattern_mismatch"),
])
def test_rejections_say_why(raw, reason):
    plate = c(raw)
    assert not plate.valid
    assert reason in plate.reasons


def test_retired_state_codes_are_valid_but_marked():
    for code, (_, until, successor) in FORMER_STATES.items():
        plate = c(f"{code} 09 AB 1234")
        assert plate.valid and plate.state_status == "former"
        assert f"former_state_code:{code}_now_{successor}_until_{until}" in plate.notes
    assert c("TG 09 AB 1234").state_status == "current"


def test_state_tables_match_the_pipeline_list():
    assert set(CURRENT_STATES) | set(FORMER_STATES) == set(STATE_CODES)
    assert not set(CURRENT_STATES) & set(FORMER_STATES)


def test_repairs_are_suggestions_over_the_spec_pairs_only():
    assert suggest_repairs("MH 12 AB 1234") == []                      # already valid
    assert suggest_repairs("MH 12 A8 1234") == ["MH12AB1234"]          # 8 -> B in a letter position
    assert suggest_repairs("MHI2AB1234") == ["MH12AB1234"]             # I -> 1 in a digit position
    assert suggest_repairs("MH12AB12S4") == ["MH12AB1254"]             # S -> 5 in the number
    assert suggest_repairs("MH 12 0M 8882") == []                      # 0 -> O would put an O in the series: not a plate
    assert suggest_repairs("ZZZZ") == []


def test_classification_never_rewrites_or_raises():
    for raw in (None, "", "  ", "↑ 01Z 012345A", "mh-12-ab-1234", "MH12AB1234" * 5):
        plate = classify_plate(raw, TODAY)
        assert plate.text == "".join(ch for ch in (raw or "").upper() if ch.isascii() and ch.isalnum())
    assert is_indian_plate("mh-12-ab-1234", TODAY)
