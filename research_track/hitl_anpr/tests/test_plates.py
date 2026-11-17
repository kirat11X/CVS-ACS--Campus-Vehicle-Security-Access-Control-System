import pytest

from anpr_hitl.plates import STATE_CODES, check_plate, normalize_plate, plate_format


@pytest.mark.parametrize("raw, fmt", [
    ("PB 65 AB 1234", "standard"),
    ("pb-65-ab-1234", "standard"),
    ("CH01A0001", "standard"),          # one series letter
    ("DL 01 CAB 1234", "standard"),     # three series letters
    ("KA53MH3895", "standard"),
    ("22 BH 1234 AA", "bh"),
    ("21BH0001XY", "bh"),
])
def test_valid_formats(raw, fmt):
    check = check_plate(raw)
    assert (check.regex_valid, check.format) == (True, fmt)
    assert "regex_invalid" not in check.flags


@pytest.mark.parametrize("raw", [
    "", "IND", "PB651234",            # no series letters
    "PB6AB1234",                       # one-digit RTO (spec requires NN)
    "PB65ABCD1234",                    # four series letters
    "PB65AB123",                       # three-digit number
    "22BH1234A",                       # BH needs two trailing letters
    "BH221234AA",
    "DUSTER", "BLUR",
])
def test_invalid_formats(raw):
    assert check_plate(raw).regex_valid is False


def test_normalization_drops_spacing_punctuation_and_other_scripts():
    assert normalize_plate(" mh.12-ab 1234 ") == "MH12AB1234"
    assert normalize_plate("पंजाब PB 10") == "PB10"
    assert normalize_plate(None) == ""


def test_confusion_table_suggests_but_never_rewrites():
    check = check_plate("GJO1HW3542")       # letter O where the RTO digits belong
    assert check.text == "GJO1HW3542"        # the read is kept exactly
    assert check.regex_valid is False
    assert "GJ01HW3542" in check.confusion_suggestions
    assert "confusion_suggestion" in check.flags


def test_confusion_pairs_are_only_the_spec_pairs():
    # Z/2 is not in the table: no suggestion may come from it.
    assert check_plate("MH1ZAB1234").confusion_suggestions == ()


@pytest.mark.parametrize("raw", ["MH12AB1234", "PB65AS1234", "DL01CAB1234", "22BH1234AB", "KA05MB8051", "TN10S5555"])
def test_valid_reads_have_no_valid_confusion_twin(raw):
    # With the four spec pairs a swap always moves a character across the letter/digit boundary, which
    # breaks the fixed 4-digit block (or the 2-digit RTO), so a valid read cannot turn into another one.
    check = check_plate(raw)
    assert check.regex_valid and check.confusion_suggestions == () and "ambiguous_confusion" not in check.flags


def test_unknown_state_is_a_separate_flag():
    check = check_plate("ZZ12AB1234")
    assert check.regex_valid and not check.state_code_known and "unknown_state" in check.flags
    assert {"PB", "CH", "DL", "KA", "MH", "TG", "TS"} <= STATE_CODES


def test_low_character_confidence_flags_positions():
    check = check_plate("PB65AB1234", char_confs=[0.99] * 4 + [0.3] + [0.99] * 5, low_char_conf=0.5)
    assert check.low_conf_positions == (4,) and "low_char_conf" in check.flags


def test_misaligned_confidences_are_flagged_not_guessed():
    check = check_plate("PB65AB1234", char_confs=[0.9, 0.9])
    assert "char_conf_misaligned" in check.flags and check.low_conf_positions == ()


def test_plate_format_helper():
    assert plate_format("22BH1234AA") == "bh" and plate_format("PB65AB1234") == "standard"
    assert plate_format("PB65AB12345") is None
