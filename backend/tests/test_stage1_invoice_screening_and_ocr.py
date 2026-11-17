"""
Regression test suite for Stage 1:
1. 3-tier matcher & 3,120-item quick-commerce taxonomy integration.
2. Ride / Logistics SERVICE category mapped to ALLOW.
3. Rupee (₹) OCR artifact normalization (弄, F, ¥, ?, Rs., INR).
4. Phantom leading 2/7 digit detection and arithmetic repair in InvoiceReconciler and parser.
5. Contraband invariant enforcement (contraband is NEVER downgraded to ALLOW).
"""
from decimal import Decimal
import pytest

from backend.app.models.enums import ScreeningVerdict
from backend.app.services.delivery_policy import (
    CategoryRule, LineScreening, classify_item, screen_line, worst, RULES, REASON_VERDICTS
)
from backend.app.services.invoice_reader import (
    OcrRow, ParsedInvoice, ParsedLine, normalize_currency_artifacts, parse_item_text, parse_rows, to_decimal
)
from research_track.track_b.src.reconciliation import InvoiceReconciler, ReconciliationStatus


def test_stage1_service_category_mapped_to_allow():
    """Verify that all ride and logistics fees map to SERVICE and ALLOW."""
    service_items = [
        "Trip Base Fare & Distance (14.2 km)",
        "Waiting & Access Fee",
        "Toll Charges (Airport Expressway)",
        "Late Night Surcharge",
        "Platform Fee",
        "Handling Charge",
        "Packaging Charge",
        "Delivery Fee",
        "Delivery Partner Fee",
        "Small Cart Fee",
        "Rain Surge Fee",
        "CGST/SGST",
        "GST Service Tax",
        "Rounding Adjustment",
    ]
    for item in service_items:
        res = screen_line(item)
        assert res.category == "SERVICE", f"Item '{item}' expected SERVICE, got {res.category}"
        assert res.verdict == ScreeningVerdict.ALLOW, f"Item '{item}' expected ALLOW, got {res.verdict}"
        assert res.reason_code in ("SERVICE_FEE_OK", "SERVICE_FEE", "SERVICE_OK")


def test_stage1_three_tier_matcher_brand_and_pack_stripping():
    """Verify brand stripping, weight stripping, and canonical root extraction."""
    cases = [
        # Brand + Staple/Oil -> ALLOW
        ("Fortune Sunlite Sunflower Oil 1L", "FOOD", ScreeningVerdict.ALLOW),
        ("Aashirvaad Shudh Chakki Atta 5kg", "FOOD", ScreeningVerdict.ALLOW),
        ("Amul Taaza Homogenised Milk 1L", "FOOD", ScreeningVerdict.ALLOW),
        ("Tata Salt Vacuum Evaporated 1kg", "FOOD", ScreeningVerdict.ALLOW),
        ("Britannia Good Day Cashew 600g", "FOOD", ScreeningVerdict.ALLOW),
        ("Harvest Gold White Bread 400g", "FOOD", ScreeningVerdict.ALLOW),
        ("Epigamia Greek Yogurt Strawberry 90g", "FOOD", ScreeningVerdict.ALLOW),
        ("Bisleri Packaged Drinking Water 5L", "BEVERAGE", ScreeningVerdict.ALLOW),
        ("Lipton Green Tea Honey Lemon 25 Bags", "BEVERAGE", ScreeningVerdict.ALLOW),
        ("Paper Boat Aamras Juice 250ml", "BEVERAGE", ScreeningVerdict.ALLOW),
        ("Colgate MaxFresh Spicy Fresh 150g", "PERSONAL_CARE", ScreeningVerdict.ALLOW),
        ("Dettol Original Germ Protection Soap (4pk)", "PERSONAL_CARE", ScreeningVerdict.ALLOW),
        # Corrosive / toxic cleaners -> REVIEW
        ("Surf Excel Matic Liquid Detergent 1L", "HAZMAT", ScreeningVerdict.REVIEW),
        ("Toilet cleaner 500 ml", "HAZMAT", ScreeningVerdict.REVIEW),
        ("Harpic Power Plus 500ml", "HAZMAT", ScreeningVerdict.REVIEW),
        ("Gainda Disinfectant Phenyl 1L", "HAZMAT", ScreeningVerdict.REVIEW),
        ("Bleach 500ml", "HAZMAT", ScreeningVerdict.REVIEW),
        # Contraband -> ALERT
        ("Classic Milds Cigarettes", "TOBACCO", ScreeningVerdict.ALERT),
        ("Kingfisher Premium Beer 650ml", "ALCOHOL", ScreeningVerdict.ALERT),
        ("Kitchen knife set 3pcs", "WEAPON", ScreeningVerdict.ALERT),
        # Unmapped -> UNKNOWN REVIEW
        ("Zxq Random Unknown Gizmo 990", "UNKNOWN", ScreeningVerdict.REVIEW),
    ]
    for item_name, exp_category, exp_verdict in cases:
        res = screen_line(item_name)
        assert res.category == exp_category, f"{item_name}: got {res.category}, expected {exp_category}"
        assert res.verdict == exp_verdict, f"{item_name}: got {res.verdict}, expected {exp_verdict}"


def test_stage1_rupee_ocr_artifact_normalization():
    """Verify normalization of currency artifacts (弄, F, ¥, ?, Rs., INR) only when preceding amounts."""
    # Test normalization helper directly
    assert normalize_currency_artifacts("Fortune Oil 1L  1  弄155.00") == "Fortune Oil 1L  1  ₹155.00"
    assert normalize_currency_artifacts("Trip Base Fare  F280.00") == "Trip Base Fare  ₹280.00"
    assert normalize_currency_artifacts("Toilet cleaner  ?99.00") == "Toilet cleaner  ₹99.00"
    assert normalize_currency_artifacts("Headphones  ¥350.00") == "Headphones  ₹350.00"

    # Crucial negative tests: normal text words starting with F or ? must NOT be altered
    assert normalize_currency_artifacts("Fortune Sunflower Oil") == "Fortune Sunflower Oil"
    assert normalize_currency_artifacts("Faasos Kitchen") == "Faasos Kitchen"
    assert normalize_currency_artifacts("Order #F-10293") == "Order #F-10293"

    # Test to_decimal on artifacts
    assert to_decimal("弄155.00") == Decimal("155.00")
    assert to_decimal("F280.00") == Decimal("280.00")
    assert to_decimal("?99.00") == Decimal("99.00")
    assert to_decimal("¥350.00") == Decimal("350.00")
    assert to_decimal("Rs. 45.00") == Decimal("45.00")
    assert to_decimal("INR 500.00") == Decimal("500.00")


def test_stage1_phantom_currency_digit_reconciliation():
    """Verify that phantom leading 2/7 digits from Rupee (₹) OCR misreads are repaired."""
    # Case 1: Line-item math with phantom 2 (e.g. ₹20.00 misread as 220.00)
    rows_line_phantom = [
        OcrRow("DEMO MART"),
        OcrRow("Order #D-9001"),
        OcrRow("Item  Qty  Amount"),
        OcrRow("Cola 750 ml  1  220.00"),  # Read as 220.00, but unit price / true value is 20.00
        OcrRow("Subtotal  20.00"),
        OcrRow("Total  20.00"),
    ]
    parsed1 = parse_rows(rows_line_phantom)
    assert parsed1.lines[0].amount == Decimal("20.00"), f"Expected phantom '2' stripped, got {parsed1.lines[0].amount}"
    assert parsed1.subtotal == Decimal("20.00")

    # Case 2: Subtotal line reconciliation with phantom 2 on one item
    rows_subtotal_phantom = [
        OcrRow("DEMO MART"),
        OcrRow("Order #D-9002"),
        OcrRow("Item  Qty  Amount"),
        OcrRow("Instant noodles 70g  4  56.00"),
        OcrRow("Cola 750 ml  2  80.00"),
        OcrRow("Toilet cleaner 500 ml  1  299.00"),  # Read as 299.00 instead of 99.00
        OcrRow("Cigarettes pack of 20  1  350.00"),
        OcrRow("Notebook A4 ruled  2  90.00"),
        OcrRow("Subtotal  675.00"),
        OcrRow("Delivery  25.00"),
        OcrRow("Total  700.00"),
    ]
    parsed2 = parse_rows(rows_subtotal_phantom)
    assert parsed2.lines[2].amount == Decimal("99.00"), f"Expected 299.00 repaired to 99.00, got {parsed2.lines[2].amount}"
    total_lines = sum(l.amount for l in parsed2.lines)
    assert total_lines == Decimal("675.00")


def test_stage1_track_b_reconciler_phantom_digit_handling():
    """Verify Track B InvoiceReconciler repairs phantom Rupee OCR digits without failing."""
    reconciler = InvoiceReconciler()
    invoice_payload = {
        "document_id": "INV-PHANTOM-TEST",
        "supplier_name": "Test Quick Commerce",
        "invoice_number": "INV-2026-99",
        "invoice_date": "2026-11-17",
        "line_items": [
            {
                "line_item_id": "line-1",
                "description": "Amul Milk 1L",
                "quantity": "2",
                "unit_price": "36.00",
                "line_total": "272.00",  # Misread as 272.00 instead of 72.00
            }
        ],
        "totals": {
            "subtotal": "72.00",
            "grand_total": "72.00",
        }
    }
    report = reconciler.reconcile(invoice_payload, schema_valid=True)
    # The reconciler should repair the line total and achieve clean reconciliation
    assert report.status in (ReconciliationStatus.RECONCILED, ReconciliationStatus.RECONCILED_WITH_WARNINGS)
    assert report.critical_count == 0
    assert report.error_count == 0
