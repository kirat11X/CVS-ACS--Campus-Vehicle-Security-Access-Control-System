"""
Comprehensive Review Tests for Track B:
- FieldNormalizer (Decimal math, currency parsing, date parsing, unit canonicalization)
- DeterministicValidator (Mandatory fields, currency consistency, line arithmetic, totals)
- InvoiceReconciler (Schema errors, critical errors, discrepancies, clean pass)
- Evaluation & Optimal Bipartite Line-Item Alignment
- DeterministicBaselineExtractor
- InvoicePipeline from config
"""

from decimal import Decimal
import json
import unittest
try:
    import pytest
except ImportError:
    pytest = None

from research_track.track_b.src.normalization import FieldNormalizer
from research_track.track_b.src.validation import (
    DeterministicValidator,
    ValidationFinding,
    ValidationSeverity,
    ReasonCode,
)
from research_track.track_b.src.reconciliation import (
    InvoiceReconciler,
    ReconciliationReport,
    ReconciliationStatus,
    ReviewActionRecommendation,
)
from research_track.track_b.src.extraction_interface import (
    DocumentReference,
    ExtractionCandidate,
    ExtractionResult,
    SchemaValidator,
)
from research_track.track_b.src.baseline_extractor import DeterministicBaselineExtractor
from research_track.track_b.src.evaluation import (
    token_similarity,
    LineItemAlignment,
    DocumentEvaluationSummary,
    BenchmarkAggregateSummary,
    MetricCalculator,
)
from research_track.track_b.src.pipeline import InvoicePipeline


# ==============================================================================
# 1. Field Normalizer Tests
# ==============================================================================

def test_field_normalizer_decimal_and_currency():
    norm = FieldNormalizer()

    # parse_decimal_amount
    assert norm.parse_decimal_amount("1234.50") == Decimal("1234.50")
    assert norm.parse_decimal_amount(1234.50) == Decimal("1234.50")
    assert norm.parse_decimal_amount(100) == Decimal("100")
    assert norm.parse_decimal_amount("1,234.50") == Decimal("1234.50")
    assert norm.parse_decimal_amount("1.234,50", locale_hint="de") == Decimal("1234.50")
    assert norm.parse_decimal_amount("50,00", locale_hint="de") == Decimal("50.00")
    assert norm.parse_decimal_amount("1,23,456.78") == Decimal("123456.78")
    assert norm.parse_decimal_amount("1,23,456") == Decimal("123456")
    assert norm.parse_decimal_amount("(150.00)") == Decimal("-150.00")
    assert norm.parse_decimal_amount("150.00-") == Decimal("-150.00")
    assert norm.parse_decimal_amount("-150.00") == Decimal("-150.00")
    assert norm.parse_decimal_amount(None) is None
    assert norm.parse_decimal_amount("invalid_number") is None

    # parse_currency
    curr, rem = norm.parse_currency("₹ 1,500.50 /-")
    assert curr == "INR"

    curr_usd, _ = norm.parse_currency("$49.99")
    assert curr_usd == "USD"

    curr_eur, _ = norm.parse_currency("EUR 120.00")
    assert curr_eur == "EUR"

    curr_def, _ = norm.parse_currency("250.00")
    assert curr_def is None


def test_field_normalizer_dates_and_units():
    norm_day = FieldNormalizer(ambiguous_date_policy="DAY_FIRST")
    norm_month = FieldNormalizer(ambiguous_date_policy="MONTH_FIRST")

    # parse_date
    assert norm_day.parse_date("2026-10-15") == "2026-10-15"
    assert norm_day.parse_date("15/10/2026") == "2026-10-15"
    assert norm_day.parse_date("04/05/2026") == "2026-05-04"  # 4th May
    assert norm_month.parse_date("04/05/2026") == "2026-04-05"  # 5th April
    assert norm_day.parse_date(None) is None
    assert norm_day.parse_date("not-a-date") is None

    # normalize_unit
    assert norm_day.normalize_unit("kgs") == "KG"
    assert norm_day.normalize_unit("litres") == "LTR"
    assert norm_day.normalize_unit("pcs") == "PCS"
    assert norm_day.normalize_unit("box") == "BOX"
    assert norm_day.normalize_unit("custom_barrel") == "CUSTOM_BARREL"
    assert norm_day.normalize_unit(None) is None

    # normalize_line_item
    norm_item = norm_day.normalize_line_item(
        raw_description="  Industrial Solvent 99%  ",
        raw_quantity="2.5",
        raw_unit_price="400.00",
        raw_unit="litres",
        raw_line_total="1000.00",
        bounding_box=[10.0, 10.0, 50.0, 50.0],
        source_page=2,
        raw_text_snippet="sample snippet",
    )
    assert norm_item["description"] == "Industrial Solvent 99%"
    assert norm_item["quantity"] == Decimal("2.5")
    assert norm_item["unit"] == "LTR"
    assert norm_item["line_total"] == Decimal("1000.00")
    assert norm_item["evidence"]["page"] == 2


# ==============================================================================
# 2. Deterministic Validator Tests
# ==============================================================================

def test_deterministic_validator_findings():
    validator = DeterministicValidator()

    # Clean invoice -> No findings
    clean_inv = {
        "supplier_name": "Supplier A",
        "invoice_number": "INV-001",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "totals": {
            "subtotal": Decimal("200.00"),
            "tax_total": Decimal("10.00"),
            "grand_total": Decimal("210.00"),
        },
        "line_items": [
            {
                "line_item_id": "L1",
                "description": "Item 1",
                "quantity": Decimal("2"),
                "unit_price": Decimal("100.00"),
                "line_total": Decimal("200.00"),
                "tax_amount": Decimal("10.00"),
                "tax_rate": Decimal("5.00"),
                "currency": "INR",
            }
        ]
    }
    findings = validator.validate_invoice(clean_inv)
    assert len(findings) == 0

    # Test Missing mandatory fields
    bad_meta_inv = {
        "totals": {
            "subtotal": Decimal("100.00"),
            "grand_total": Decimal("100.00"),
        },
        "line_items": [
            {"line_item_id": "L1", "description": "Item", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}
        ]
    }
    f_meta = validator.validate_invoice(bad_meta_inv)
    codes_meta = [f.code for f in f_meta]
    assert ReasonCode.VAL_MISSING_MANDATORY_FIELD in codes_meta

    # Test Line Arithmetic Mismatch & Negative Quantity
    bad_line_inv = {
        "supplier_name": "Supplier A",
        "invoice_number": "INV-002",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "totals": {
            "subtotal": Decimal("100.00"),
            "grand_total": Decimal("100.00"),
        },
        "line_items": [
            {
                "line_item_id": "L1",
                "description": "Item 1",
                "quantity": Decimal("-2"),
                "unit_price": Decimal("100.00"),
                "line_total": Decimal("500.00"),  # Mismatch: -2 * 100 != 500
            },
            {
                "line_item_id": "L2",
                "description": "Item 1",  # Duplicate description
                "quantity": Decimal("1"),
                "unit_price": Decimal("-50.00"),  # Negative unit price
                "line_total": Decimal("-50.00"),
                "currency": "USD",  # Currency inconsistency
            }
        ]
    }
    f_line = validator.validate_invoice(bad_line_inv)
    codes_line = [f.code for f in f_line]
    assert ReasonCode.VAL_NEGATIVE_QUANTITY in codes_line
    assert ReasonCode.VAL_NEGATIVE_UNIT_PRICE in codes_line
    assert ReasonCode.VAL_LINE_ARITHMETIC_MISMATCH in codes_line
    assert ReasonCode.VAL_CURRENCY_INCONSISTENCY in codes_line
    assert ReasonCode.VAL_DUPLICATE_ITEM_DESCRIPTION in codes_line

    # Test Subtotal and Grand Total Mismatches
    bad_totals_inv = {
        "supplier_name": "Supplier A",
        "invoice_number": "INV-003",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "totals": {
            "subtotal": Decimal("500.00"),     # Actual line sum is 100.00
            "tax_total": Decimal("50.00"),
            "grand_total": Decimal("999.00"), # 500 + 50 != 999
            "amount_paid": Decimal("100.00"),
            "amount_due": Decimal("500.00"),  # 999 - 100 != 500
        },
        "line_items": [
            {"line_item_id": "L1", "description": "Item 1", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}
        ]
    }
    f_totals = validator.validate_invoice(bad_totals_inv)
    codes_totals = [f.code for f in f_totals]
    assert ReasonCode.VAL_SUBTOTAL_MISMATCH in codes_totals
    assert ReasonCode.VAL_GRAND_TOTAL_MISMATCH in codes_totals
    assert ReasonCode.VAL_PAYMENT_BALANCE_MISMATCH in codes_totals


# ==============================================================================
# 3. Invoice Reconciler Tests
# ==============================================================================

def test_invoice_reconciler_statuses():
    reconciler = InvoiceReconciler()

    # 1. Schema violation
    rep_schema = reconciler.reconcile({"document_id": "bad_doc"}, schema_valid=False)
    assert rep_schema.status == ReconciliationStatus.SCHEMA_VALIDATION_ERROR
    assert rep_schema.recommendation == ReviewActionRecommendation.REJECT_INVALID_DATA
    assert rep_schema.critical_count == 1
    assert rep_schema.requires_human_review is True

    # 2. Critical arithmetic failure (grand total mismatch is critical)
    crit_inv = {
        "document_id": "doc-crit",
        "supplier_name": "S",
        "invoice_number": "1",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "totals": {
            "subtotal": Decimal("100.00"),
            "tax_total": Decimal("10.00"),
            "grand_total": Decimal("500.00"),  # Critical mismatch
        },
        "line_items": [
            {"line_item_id": "L1", "description": "I", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}
        ]
    }
    rep_crit = reconciler.reconcile(crit_inv, schema_valid=True)
    assert rep_crit.status == ReconciliationStatus.CRITICAL_ARITHMETIC_FAILURE
    assert rep_crit.recommendation == ReviewActionRecommendation.QUEUE_FOR_HUMAN_REVIEW

    # 3. Reconciled with warnings (e.g. missing invoice date is a warning)
    warn_inv = {
        "document_id": "doc-warn",
        "supplier_name": "S",
        "invoice_number": "1",
        "currency": "INR",
        "totals": {
            "subtotal": Decimal("100.00"),
            "tax_total": Decimal("0.00"),
            "grand_total": Decimal("100.00"),
        },
        "line_items": [
            {"line_item_id": "L1", "description": "I", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}
        ]
    }
    rep_warn = reconciler.reconcile(warn_inv, schema_valid=True)
    assert rep_warn.status == ReconciliationStatus.RECONCILED_WITH_WARNINGS
    assert rep_warn.warning_count > 0

    # 4. Perfectly reconciled
    clean_inv = {
        "document_id": "doc-clean",
        "supplier_name": "S",
        "invoice_number": "1",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "totals": {
            "subtotal": Decimal("100.00"),
            "tax_total": Decimal("0.00"),
            "grand_total": Decimal("100.00"),
        },
        "line_items": [
            {"line_item_id": "L1", "description": "I", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}
        ]
    }
    rep_clean = reconciler.reconcile(clean_inv, schema_valid=True)
    assert rep_clean.status == ReconciliationStatus.RECONCILED
    assert rep_clean.recommendation == ReviewActionRecommendation.ACCEPT_CONFIDENT
    assert rep_clean.requires_human_review is False


# ==============================================================================
# 4. Evaluation & Bipartite Line-Item Alignment Tests
# ==============================================================================

def test_evaluation_and_bipartite_alignment():
    calc = MetricCalculator()

    # token similarity
    assert token_similarity("A4 Paper", "A4 Paper") == 1.0
    assert token_similarity("A4 Paper", "Photo Paper") == 1 / 3
    assert token_similarity("", "") == 1.0
    assert token_similarity("A4", None) == 0.0

    # Bipartite alignment: 2 predicted items vs 2 ground-truth items
    pred_items = [
        {"description": "HP A4 Paper", "quantity": 2, "unit_price": "250.00", "line_total": "500.00"},
        {"description": "Ballpoint Pens Blue", "quantity": 10, "unit_price": "10.00", "line_total": "100.00"},
    ]
    gt_items = [
        {"description": "Ballpoint Pens Blue Pack", "quantity": 10, "unit_price": "10.00", "line_total": "100.00"},
        {"description": "HP A4 Printer Paper", "quantity": 2, "unit_price": "250.00", "line_total": "500.00"},
    ]

    alignments = calc.align_line_items(pred_items, gt_items)
    assert len(alignments) == 2
    assert alignments[0].line_total_exact is True

    # evaluate_document
    pred_doc = {
        "document_id": "DOC-1",
        "supplier_name": "Office Depot",
        "invoice_number": "INV-99",
        "invoice_date": "2026-05-01",
        "currency": "USD",
        "total_amount": "600.00",
        "line_items": pred_items,
    }
    gt_doc = {
        "document_id": "DOC-1",
        "supplier_name": "Office Depot",
        "invoice_number": "INV-99",
        "invoice_date": "2026-05-01",
        "currency": "USD",
        "total_amount": "600.00",
        "line_items": gt_items,
    }

    doc_summary = calc.evaluate_document(pred_doc, gt_doc, schema_valid=True, reconciled=True, latency_ms=18.5)
    assert doc_summary.document_id == "DOC-1"
    assert doc_summary.line_item_precision == 1.0
    assert doc_summary.line_item_recall == 1.0
    assert doc_summary.line_item_f1 == 1.0
    assert doc_summary.invoice_number_exact is True
    assert doc_summary.grand_total_exact is True
    assert doc_summary.to_dict()["document_id"] == "DOC-1"

    # compute_aggregate_summary
    agg = calc.compute_aggregate_summary([doc_summary], benchmark_type="synthetic")
    assert agg.total_documents == 1
    assert agg.schema_valid_rate == 1.0
    assert agg.reconciliation_pass_rate == 1.0
    assert agg.to_dict()["total_documents"] == 1
    md_table = agg.format_markdown_table()
    assert "Benchmark Evaluation Summary" in md_table


# ==============================================================================
# 5. Baseline Extractor & Pipeline Tests
# ==============================================================================

def test_deterministic_baseline_extractor_and_pipeline():
    extractor = DeterministicBaselineExtractor()
    doc_text = """
    Invoice Number: INV-2026-0042
    Invoice Date: 2026-07-20
    Supplier: Campus Catering Services
    Currency: INR

    Line Items:
    Mineral Water 1L | 10 | 20.00 | 200.00
    Veg Sandwich | 5 | 50.00 | 250.00

    Subtotal: 450.00
    Tax: 0.00
    Grand Total: 450.00
    """
    doc_ref = DocumentReference(document_id="DOC-CATERING-42")
    res = extractor.extract(doc_ref, doc_text)
    assert isinstance(res, ExtractionResult)
    assert res.document_id == "DOC-CATERING-42"
    assert len(res.candidates) > 0
    selected = res.candidates[0].invoice
    assert selected["invoice_number"] == "INV-2026-0042"
    assert selected["supplier_name"] == "Campus Catering Services"

    # InvoicePipeline from_config
    pipeline = InvoicePipeline.from_config("research_track/track_b/config.yaml")
    assert pipeline.extractor is not None
    assert pipeline.validator is not None
    assert pipeline.reconciler is not None


def test_fallback_schema_validator(monkeypatch=None):
    import research_track.track_b.src.extraction_interface as ei
    orig = getattr(ei, "_HAS_JSONSCHEMA", False)
    ei._HAS_JSONSCHEMA = False

    # 1. Non-dict payload
    ok, errs = ei.SchemaValidator.validate_invoice_dict("not_a_dict")
    assert not ok
    assert "Root invoice payload must be a JSON object" in errs[0]

    # 2. Missing required root field
    ok, errs = ei.SchemaValidator.validate_invoice_dict({"supplier_name": "Test"})
    assert not ok
    assert any("required property" in e for e in errs)

    # 3. Invalid line_items type
    ok, errs = ei.SchemaValidator.validate_invoice_dict({
        "document_id": "D1",
        "supplier_name": "S",
        "invoice_number": "1",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "line_items": "not_a_list",
        "totals": {"total_amount": "100.00"},
        "extraction_metadata": {"extractor_name": "test", "extractor_version": "1.0"},
    })
    assert not ok
    assert any("'line_items' must be an array" in e for e in errs)

    # 4. Line item with missing required property or extra property
    ok, errs = ei.SchemaValidator.validate_invoice_dict({
        "document_id": "D1",
        "supplier_name": "S",
        "invoice_number": "1",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "line_items": [
            "not_an_object",
            {"description": "Item", "unexpected_field": "bad"},
        ],
        "totals": {"total_amount": "100.00", "unexpected_total": "bad"},
        "extraction_metadata": {"extractor_name": "test", "extractor_version": "1.0", "extra_meta": 1},
    })
    assert not ok
    assert any("item must be an object" in e for e in errs)

    # 5. Invalid totals type
    ok, errs = ei.SchemaValidator.validate_invoice_dict({
        "document_id": "D1",
        "supplier_name": "S",
        "invoice_number": "1",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "line_items": [],
        "totals": "not_an_object",
        "extraction_metadata": {},
    })
    assert not ok
    assert any("'totals' must be an object" in e for e in errs)

    # 6. Invalid extraction_metadata type
    ok, errs = ei.SchemaValidator.validate_invoice_dict({
        "document_id": "D1",
        "supplier_name": "S",
        "invoice_number": "1",
        "invoice_date": "2026-01-01",
        "currency": "INR",
        "line_items": [],
        "totals": {"total_amount": "100.00"},
        "extraction_metadata": "not_an_object",
    })
    assert not ok
    assert any("'extraction_metadata' must be an object" in e for e in errs)

    ei._HAS_JSONSCHEMA = orig


def test_track_b_pipeline_evaluate_corpus():
    pipeline = InvoicePipeline.from_config("research_track/track_b/config.yaml")

    inv_text = """
    Invoice Number: INV-CORPUS-1
    Invoice Date: 2026-08-01
    Supplier: Campus Store
    Currency: INR
    Line Items:
    Notebook A5 | 2 | 50.00 | 100.00
    Subtotal: 100.00
    Total: 100.00
    """
    invoices = [
        {"document_id": "DOC-C1", "raw_text": inv_text, "category": "single_line"}
    ]
    gt_map = {
        "DOC-C1": {
            "document_id": "DOC-C1",
            "invoice_number": "INV-CORPUS-1",
            "invoice_date": "2026-08-01",
            "supplier_name": "Campus Store",
            "currency": "INR",
            "total_amount": "100.00",
            "line_items": [
                {"description": "Notebook A5", "quantity": 2, "unit_price": "50.00", "line_total": "100.00"}
            ]
        }
    }

    agg = pipeline.evaluate_corpus(invoices, gt_map, benchmark_type="test_corpus")
    assert agg.total_documents == 1
    assert agg.schema_valid_rate == 1.0


def test_reconciler_reexport():
    import research_track.track_b.src.reconciler as rec_alias
    assert rec_alias.InvoiceReconciler is not None
    assert rec_alias.ReconciliationStatus is not None


class TrackBFullTest(unittest.TestCase):
    def test_decimal_and_currency(self):
        test_field_normalizer_decimal_and_currency()

    def test_dates_and_units(self):
        test_field_normalizer_dates_and_units()

    def test_validator_findings(self):
        test_deterministic_validator_findings()

    def test_reconciler_statuses(self):
        test_invoice_reconciler_statuses()

    def test_bipartite_alignment(self):
        test_evaluation_and_bipartite_alignment()

    def test_baseline_and_pipeline(self):
        test_deterministic_baseline_extractor_and_pipeline()

    def test_fallback_validator(self):
        test_fallback_schema_validator()

    def test_evaluate_corpus(self):
        test_track_b_pipeline_evaluate_corpus()

    def test_reexport(self):
        test_reconciler_reexport()


if __name__ == "__main__":
    unittest.main()

