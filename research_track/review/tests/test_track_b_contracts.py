import copy
import json
from decimal import Decimal
import unittest

from research_track.track_b.src.extraction_interface import SchemaValidator
from research_track.track_b.src.normalization import FieldNormalizer
from research_track.track_b.src.reconciliation import InvoiceReconciler


def _ground_truth_invoice():
    with open("research_track/track_b/fixtures/synthetic_ground_truth.json", encoding="utf-8") as f:
        raw = json.load(f)
    return raw[0] if isinstance(raw, list) else next(iter(raw.values()))


def test_track_b_schema_accepts_fixture_and_rejects_unexpected_property():
    invoice = _ground_truth_invoice()
    valid, errors = SchemaValidator.validate_invoice_dict(invoice)
    assert valid, errors
    invalid = copy.deepcopy(invoice)
    invalid["unexpected"] = "must be rejected"
    valid, errors = SchemaValidator.validate_invoice_dict(invalid)
    assert not valid
    assert any("unexpected" in error for error in errors)


def test_track_b_schema_rejection_is_serializable():
    report = InvoiceReconciler().reconcile({"document_id": "bad"}, schema_valid=False)
    assert report.to_dict()["findings"][0]["code"] == "VAL_SCHEMA_VIOLATION"


def test_track_b_decimal_normalization_round_trips_without_binary_float():
    normalizer = FieldNormalizer()
    value = normalizer.parse_decimal_amount("1.234,50", locale_hint="de")
    assert value == Decimal("1234.50")
    assert str(value) == "1234.50"


class TrackBContractsTest(unittest.TestCase):
    def test_schema_accepts_fixture_and_rejects_unexpected_property(self):
        test_track_b_schema_accepts_fixture_and_rejects_unexpected_property()

    def test_schema_rejection_is_serializable(self):
        test_track_b_schema_rejection_is_serializable()

    def test_decimal_normalization_round_trips_without_binary_float(self):
        test_track_b_decimal_normalization_round_trips_without_binary_float()


if __name__ == "__main__":
    unittest.main()
