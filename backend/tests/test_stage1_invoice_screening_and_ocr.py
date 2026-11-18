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
from backend.app.services.delivery_screening_service import DeliveryScreeningService
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


def test_mobile_app_screenshot_layout_parsing():
    """
    Verifies that modern quick-commerce app screenshots (e.g. Blinkit/Swiggy/Zepto)
    with multi-line item layouts, struck-out MRPs, and phantom Rupee OCR artifacts
    are parsed and reconciled to the exact total.
    """
    rows = [
        OcrRow("Order details"),
        OcrRow("Delivered in 10 minutes"),
        OcrRow("5 items in order"),
        OcrRow("TataTeaGold-AssamTea  180"),
        OcrRow("250 g · 1unit"),
        OcrRow("SaffolaClassicMasalaOats  320"),  # ₹20 misread with phantom leading 3
        OcrRow("38 g · 1 unit"),
        OcrRow("Rajdhani Dalia  43"),
        OcrRow("500 g - 1 unit  455"),  # Crossed-out MRP
        OcrRow("Fresh Hybrid Tomato  23"),
        OcrRow("500 g · 1 unit  58"),
        OcrRow("Farmley Smokey BBQ Party Mix  45"),
        OcrRow("28 g - 1 unit  50"),
        OcrRow("Bill summary"),
        OcrRow("Items total  1363  311"),
        OcrRow("Handling fee  10  FREE"),
        OcrRow("Delivery fee  30  FREE"),
        OcrRow("You pay  ￥403  311"),
    ]

    parsed = parse_rows(rows)
    assert len(parsed.lines) == 5
    assert parsed.total == Decimal("311.00")
    assert parsed.lines[0].item_name == "TataTeaGold-AssamTea"
    assert parsed.lines[0].amount == Decimal("180.00")
    # Saffola Oats: 320.00 repaired to 20.00 via phantom '3' removal
    assert parsed.lines[1].amount == Decimal("20.00")
    assert parsed.lines[2].amount == Decimal("43.00")
    assert parsed.lines[3].amount == Decimal("23.00")
    assert parsed.lines[4].amount == Decimal("45.00")

    # Complete arithmetic matches total
    sum_lines = sum(l.amount for l in parsed.lines)
    assert sum_lines == parsed.total == Decimal("311.00")


def test_multi_word_allow_plus_alert_items():
    """
    Verifies that multi-word compound line items combining safe food (ALLOW)
    and restricted contraband (ALERT) always resolve to ALERT.
    Contraband must NEVER be downgraded by companion food words.
    """
    from backend.app.services.cvs_acs_screener import cvs_acs_screener

    mixed_items = [
        "Egg Roll and Beer",
        "Harvest Gold Bread and Kingfisher Beer 650ml",
        "White Bread with Kitchen Knife",
        "Blueberry Cake with Marlboro Cigarettes",
        "Amul Milk and Classic Milds Cigarettes",
        "Tata Tea Gold with Country Liquor",
        "Chicken Biryani and Vodka",
        "Blueberry Cake with Lighter Fluid",
    ]

    for item in mixed_items:
        # 1. Test deterministic delivery policy
        rule, kw = classify_item(item)
        assert rule.verdict == ScreeningVerdict.ALERT, (
            f"Policy failed for '{item}': expected ALERT, got {rule.verdict} (keyword: {kw})"
        )

        # 2. Test CVS-ACS candidate retriever & screener
        scr = cvs_acs_screener.screen_item(item)
        assert scr["verdict"] == "ALERT", (
            f"CVS-ACS screener failed for '{item}': expected ALERT, got {scr['verdict']}"
        )

    # Mixed items with HAZMAT/review keywords should resolve to REVIEW over ALLOW
    hazmat_items = [
        "White Bread with Harpic 500ml",
        "Tata Tea Gold with Rat Poison",
        "Amul Milk with Crocin Tablets",
    ]
    for item in hazmat_items:
        rule, kw = classify_item(item)
        assert rule.verdict == ScreeningVerdict.REVIEW, (
            f"Policy failed for '{item}': expected REVIEW, got {rule.verdict} (keyword: {kw})"
        )

    # Verify candidate retrieval collects matches across ALL tokens
    cands = cvs_acs_screener.retrieve_candidate_matches("Egg Roll and Beer")
    cand_verdicts = [c.get("verdict") for c in cands]
    assert "ALERT" in cand_verdicts, f"Expected ALERT candidate in matches across all tokens: {cands}"


def test_totals_match_false_escalation_to_review():
    """
    Verifies that whenever totals_match is False (arithmetic discrepancy or missing line price),
    the overall screening verdict is escalated to REVIEW even if every individual line is ALLOW.
    """
    # Case 1: All items are ALLOW, but sum(lines) != total printed -> overall escalates to REVIEW
    lines_allow = [
        ParsedLine(
            line_no=1,
            item_name="Harvest Gold White Bread 400g",
            quantity=1,
            unit_price=Decimal("40.00"),
            amount=Decimal("40.00"),
            confidence=1.0,
            readable=True,
        ),
        ParsedLine(
            line_no=2,
            item_name="Amul Taaza Homogenised Milk 1L",
            quantity=1,
            unit_price=Decimal("60.00"),
            amount=Decimal("60.00"),
            confidence=1.0,
            readable=True,
        ),
    ]
    parsed_mismatch = ParsedInvoice(
        lines=lines_allow,
        subtotal=Decimal("100.00"),
        total=Decimal("250.00"),  # Mismatches items sum of 100.00!
        order_number="D-9901",
    )
    result = DeliveryScreeningService.screen(parsed_mismatch, "D-9901")
    assert result.totals_match is False
    assert result.overall == ScreeningVerdict.REVIEW, (
        f"Expected overall to escalate to REVIEW on totals mismatch, got {result.overall}"
    )

    # Case 2: One item is ALERT, and totals_match is False -> overall remains ALERT (ALERT > REVIEW)
    lines_with_alert = [
        ParsedLine(
            line_no=1,
            item_name="Amul Taaza Milk 1L",
            quantity=1,
            unit_price=Decimal("60.00"),
            amount=Decimal("60.00"),
            confidence=1.0,
            readable=True,
        ),
        ParsedLine(
            line_no=2,
            item_name="Classic Milds Cigarettes",
            quantity=1,
            unit_price=Decimal("350.00"),
            amount=Decimal("350.00"),
            confidence=1.0,
            readable=True,
        ),
    ]
    parsed_alert = ParsedInvoice(
        lines=lines_with_alert,
        subtotal=Decimal("410.00"),
        total=Decimal("600.00"),  # Discrepancy
        order_number="D-9902",
    )
    result_alert = DeliveryScreeningService.screen(parsed_alert, "D-9902")
    assert result_alert.totals_match is False
    assert result_alert.overall == ScreeningVerdict.ALERT, (
        f"Expected overall ALERT to be preserved over REVIEW, got {result_alert.overall}"
    )

    # Case 3: Line amount is missing (None) with a printed total -> totals_match is False, overall is REVIEW
    lines_unreadable_amount = [
        ParsedLine(
            line_no=1,
            item_name="Harvest Gold Bread",
            quantity=1,
            unit_price=None,
            amount=None,
            confidence=0.5,
            readable=True,
        ),
    ]
    parsed_missing_amt = ParsedInvoice(
        lines=lines_unreadable_amount,
        total=Decimal("40.00"),
        order_number="D-9903",
    )
    result_missing = DeliveryScreeningService.screen(parsed_missing_amt, "D-9903")
    assert result_missing.totals_match is False
    assert result_missing.overall == ScreeningVerdict.REVIEW


def test_missing_verdict_failsafe_behavior():
    """
    Verifies that missing, None, or invalid verdicts from screener or items
    fail-safe to REVIEW rather than ALLOW.
    """
    from unittest.mock import patch
    from backend.app.services.cvs_acs_screener import cvs_acs_screener

    # Case 1: Missing verdict key in screener response
    with patch.object(cvs_acs_screener, "screen_item", return_value={"item_name": "Mystery Box", "category": "PARCEL"}):
        parsed = ParsedInvoice(
            lines=[
                ParsedLine(
                    line_no=1,
                    item_name="Mystery Box",
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    amount=Decimal("100.00"),
                    confidence=1.0,
                    readable=True,
                )
            ],
            total=Decimal("100.00"),
            order_number="D-9904",
        )
        res = DeliveryScreeningService.screen(parsed, "D-9904")
        assert res.lines[0].verdict == ScreeningVerdict.REVIEW
        assert res.overall == ScreeningVerdict.REVIEW

    # Case 2: Invalid verdict string in screener response
    with patch.object(cvs_acs_screener, "screen_item", return_value={"item_name": "Mystery Box", "verdict": "INVALID_VAL"}):
        parsed = ParsedInvoice(
            lines=[
                ParsedLine(
                    line_no=1,
                    item_name="Mystery Box",
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    amount=Decimal("100.00"),
                    confidence=1.0,
                    readable=True,
                )
            ],
            total=Decimal("100.00"),
            order_number="D-9905",
        )
        res = DeliveryScreeningService.screen(parsed, "D-9905")
        assert res.lines[0].verdict == ScreeningVerdict.REVIEW
        assert res.overall == ScreeningVerdict.REVIEW

    # Case 3: Empty string passed to cvs_acs_screener
    res_empty = cvs_acs_screener.screen_item("")
    assert res_empty["verdict"] == "REVIEW"
    assert res_empty["is_uncertain"] is True


def test_ollama_keep_alive_and_async_wrappers():
    """
    Verifies that OLLAMA_KEEP_ALIVE defaults to '5m' and is configurable,
    and that async wrappers execute properly via asyncio.to_thread.
    """
    import asyncio
    from backend.app.services.cvs_acs_screener import cvs_acs_screener, CVSACSScreener
    from backend.app.services.llm_invoice_extractor import llm_invoice_extractor, LLMInvoiceExtractor

    assert cvs_acs_screener.keep_alive == "5m"
    assert llm_invoice_extractor.keep_alive == "5m"

    custom_screener = CVSACSScreener(keep_alive="10m")
    assert custom_screener.keep_alive == "10m"

    custom_extractor = LLMInvoiceExtractor(keep_alive="10m")
    assert custom_extractor.keep_alive == "10m"

    # Async wrapper tests
    async def run_async_tests():
        res = await cvs_acs_screener.screen_item_async("Amul Milk 1L")
        assert res["verdict"] == "ALLOW"

        extracted = await llm_invoice_extractor.extract_from_text_async("")
        assert extracted is not None

    asyncio.run(run_async_tests())


def test_profile_manager_concurrency_and_thread_safety(tmp_path):
    """
    Verifies that TelegramProfileManager guards _profiles and _save with a lock
    under concurrent read/write stress without race conditions or data corruption.
    """
    import concurrent.futures
    from backend.app.telegram.profile_manager import TelegramProfileManager
    from backend.app.db import SessionLocal
    from backend.app.models.identity import TelegramUser, VehicleOwner

    temp_storage = tmp_path / "concurrent_profiles.json"
    pm = TelegramProfileManager(storage_path=temp_storage)

    base_chat_id = 991000

    def worker(offset: int):
        cid = base_chat_id + offset
        pm.save_profile(
            cid,
            full_name=f"User {cid}",
            identifier=f"P7-STU{cid}",
            location="Aravali Hostel",
            username=f"user_{cid}",
        )
        pm.record_visit(cid)
        pm.update_location(cid, "Kurukshetra Hostel")
        assert pm.is_registered(cid) is True
        prof = pm.get_profile(cid)
        assert prof is not None
        assert prof["location"] == "Kurukshetra Hostel"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(20)]
            for f in concurrent.futures.as_completed(futures):
                f.result()

        # Verify all 20 profiles persisted correctly
        for i in range(20):
            cid = base_chat_id + i
            prof = pm.get_profile(cid)
            assert prof is not None
            assert prof["full_name"] == f"User {cid}"
    finally:
        try:
            with SessionLocal() as db:
                db.query(TelegramUser).filter(
                    TelegramUser.chat_id >= base_chat_id,
                    TelegramUser.chat_id < base_chat_id + 100,
                ).delete(synchronize_session=False)
                db.query(VehicleOwner).filter(
                    VehicleOwner.identifier.like(f"P7-STU{base_chat_id}%")
                ).delete(synchronize_session=False)
                db.commit()
        except Exception:
            pass


def test_zepto_platform_detection_and_discounted_pricing_snk():
    """
    Regression test for order SNKRJSISE59003:
    1. Splits fused summary numbers: 184165 -> 184 165, 223174 -> 223 174.
    2. Identifies Zepto platform from receipt UI signatures (Download Invoice/CreditNote, OrderAgain).
    3. Handles handling fee R9 -> 9.00 and calculates computed total (165 + 9 = 174).
    4. Evaluates items (Verka Paneer and Eggoz Eggs) as ALLOW.
    """
    from backend.app.services.invoice_reader import parse_mobile_order_layout, OcrRow
    from backend.app.services.delivery_screening_service import DeliveryScreeningService

    raw_snk = """1:04M  64
Order#SNKRJSISE59003  Get Help
2items
Delivered
2itemsinorder
VerkaPaneerVacuumPack  #95
1pack(200g)·1unit
EggozEverydayWhiteFarmFreshEggs  70
1pack(6pcs)1unit  68至
图Bill Summary
Item Total  184165
Delivery Fee  30FREE
Handling Fee  R9
Total Bill  223174
Download Invoice/CreditNote
OrderDetails
Order ID
#SNKRJSISE59003
ReceiverDetails
KritanshUppal,+919815000709
RateOrder  OrderAgain"""

    rows = [OcrRow(text=l, confidence=1.0) for l in raw_snk.splitlines()]
    parsed = parse_mobile_order_layout(rows)

    assert parsed.platform == "Zepto"
    assert parsed.vendor == "Zepto"
    assert parsed.order_number == "SNKRJSISE59003"
    assert parsed.subtotal == Decimal("165.00")
    assert parsed.delivery_fee == Decimal("9.00")
    assert parsed.total == Decimal("174.00")

    assert len(parsed.lines) == 2
    assert "Paneer" in parsed.lines[0].item_name
    assert parsed.lines[0].amount == Decimal("95.00")
    assert "Eggs" in parsed.lines[1].item_name
    assert parsed.lines[1].amount == Decimal("70.00")

    scr = DeliveryScreeningService.screen(parsed, "SNKRJSISE59003")
    assert scr.totals_match is True
    assert scr.computed_total == Decimal("174.00")
    assert scr.overall == ScreeningVerdict.ALLOW


def test_zepto_charging_cable_phantom_digit_and_word_boundary_jks():
    """
    Regression test for order JKSVKRPRN67992:
    1. Detects and strips systematic phantom Rupee digit '2' (2130 -> 130, 2741 -> 741).
    2. Correctly assigns platform Zepto and order number JKSVKRPRN67992.
    3. Categorizes charging cable as ELECTRONICS with verdict ALLOW.
    4. Guarantees 'charGINg' never matches 'gin' (contraband alcohol).
    """
    from backend.app.services.invoice_reader import parse_mobile_order_layout, OcrRow
    from backend.app.services.delivery_screening_service import DeliveryScreeningService
    from backend.app.services.cvs_acs_screener import cvs_acs_screener

    raw_jks = """1:03 M  oo Ball Wi SE
Order #JKSVKRPRN67992 (3.
Cl  ee  @ Get Help
v Delivered
litem in order
Portronics Konnect B+ 1m Long Charging 2130
if  Cable | USB-A to Lightning for 8 Pin US...  2499
Tpe » Vunit
&) Bill Summary
Item Total  2699 2130
Delivery Fee  230 FREE
Handling Fee  212 FREE
Total Bill  2741 2130
Download Invoice / Credit Note
Order Details
Order ID
#JKSVKRPRN67992
Delivery Address
Rs academy, XGHQ+3PR, Hussainpur, Rupnagar, Punjab 140001,
India
Order Placed at
15 Nov 2026, 7:21 PM"""

    rows = [OcrRow(text=l, confidence=1.0) for l in raw_jks.splitlines()]
    parsed = parse_mobile_order_layout(rows)

    assert parsed.platform == "Zepto"
    assert parsed.vendor == "Zepto"
    assert parsed.order_number == "JKSVKRPRN67992"
    assert parsed.total == Decimal("130.00")
    assert parsed.subtotal == Decimal("130.00")
    assert parsed.delivery_fee == Decimal("0.00")

    assert len(parsed.lines) == 1
    assert "Charging" in parsed.lines[0].item_name
    assert parsed.lines[0].amount == Decimal("130.00")

    scr = DeliveryScreeningService.screen(parsed, "JKSVKRPRN67992")
    assert scr.totals_match is True
    assert scr.computed_total == Decimal("130.00")
    assert scr.overall == ScreeningVerdict.ALLOW

    # Verify cvs_acs_screener word boundary isolation
    cable_res = cvs_acs_screener.screen_item("Portronics Konnect B+ 1m Long Charging Cable")
    assert cable_res["verdict"] == "ALLOW"
    assert "gin" not in cable_res.get("canonical_root", "")


def test_cvs_acs_screener_word_boundary_safety():
    """
    Verifies that substring keyword traps (gin in charging, rum in drumstick/serum)
    are strictly avoided using word boundaries, while real contraband is always flagged ALERT.
    """
    from backend.app.services.cvs_acs_screener import cvs_acs_screener

    # Safe items containing contraband substrings
    safe_substring_items = [
        "Portronics Konnect B+ Charging Cable",
        "Chicken Drumsticks 500g",
        "Ginger Garlic Paste 200g",
        "Vitamin C Face Serum 30ml",
    ]
    for safe_item in safe_substring_items:
        res = cvs_acs_screener.screen_item(safe_item)
        assert res["verdict"] in ("ALLOW", "REVIEW"), f"Item '{safe_item}' was wrongly flagged as {res['verdict']}"
        assert res["category"] != "PROHIBITED_CONTRABAND"

    # Actual contraband must strictly trigger ALERT
    contraband_items = [
        "Bombay Sapphire Gin 750ml",
        "Old Monk Dark Rum 750ml",
        "Marlboro Light Cigarettes",
        "Red Tobacco Leaves",
    ]
    for bad_item in contraband_items:
        res = cvs_acs_screener.screen_item(bad_item)
        assert res["verdict"] == "ALERT", f"Contraband '{bad_item}' expected ALERT, got {res['verdict']}"
        assert res["category"] == "PROHIBITED_CONTRABAND"


def test_spatial_line_by_line_ocr_formatting():
    """
    Verifies that spatial line-by-line grouping bundles bounding box fragments
    within vertical proximity and outputs '[L01] <token> (conf:0.xx) | ...' lines.
    """
    from backend.app.services.invoice_reader import _group_rows, OcrResult

    # Simulate RapidOCR fragments: (x_left, y_center, height, text, score)
    fragments = [
        (10, 100, 20, "Tata Tea Gold", 0.95),
        (200, 102, 20, "180.00", 0.92),
        (300, 101, 20, "220.00", 0.65),  # Slashed MRP
        (10, 150, 20, "Bill Total", 0.98),
        (250, 152, 20, "180.00", 0.97),
    ]

    rows = _group_rows(fragments)
    assert len(rows) == 2
    assert rows[0].formatted_line is not None
    assert rows[0].formatted_line.startswith("[L01] ")
    assert "Tata Tea Gold (conf:0.95)" in rows[0].formatted_line
    assert "180.00 (conf:0.92)" in rows[0].formatted_line
    assert "220.00 (conf:0.65)" in rows[0].formatted_line

    assert rows[1].formatted_line.startswith("[L02] ")
    assert "Bill Total (conf:0.98)" in rows[1].formatted_line

    ocr_res = OcrResult("RAPIDOCR", rows, 0.95)
    formatted_text = ocr_res.formatted_text
    assert "[L01]" in formatted_text
    assert "[L02]" in formatted_text


def test_phantom_rupee_3149_and_strikethrough_mrp_screening_reconciliation():
    """
    Verifies that:
    1. A phantom Rupee '3' (e.g. ₹149 read as 3149, or ₹180 read as 3180) is healed
       to achieve arithmetic balance with the grand total.
    2. Slashed MRP vs. discounted price pair resolution in DeliveryScreeningService.
    """
    from backend.app.services.delivery_screening_service import DeliveryScreeningService
    from backend.app.services.invoice_reader import ParsedInvoice, ParsedLine

    # Receipt with Tata Tea Gold misread as 3180 instead of 180, total is 180
    parsed = ParsedInvoice(
        lines=[
            ParsedLine(
                line_no=1,
                item_name="Tata Tea Gold, Assam Tea",
                quantity=1,
                unit_price=Decimal("3180.00"),
                amount=Decimal("3180.00"),
                confidence=0.92,
                readable=True,
                raw_text="Tata Tea Gold, Assam Tea 1unit  3180  220",
            )
        ],
        subtotal=Decimal("180.00"),
        delivery_fee=Decimal("0.00"),
        total=Decimal("180.00"),
        vendor="Blinkit",
    )

    scr = DeliveryScreeningService.screen(parsed, "TG-TEST3180")
    assert scr.totals_match is True
    assert scr.lines[0].amount == Decimal("180.00")
    assert scr.lines[0].unit_price == Decimal("180.00")
    assert scr.computed_total == Decimal("180.00")
    assert scr.overall == ScreeningVerdict.ALLOW

    # Case with Blinkit line having phantom 3149 (for ₹149 item)
    parsed_149 = ParsedInvoice(
        lines=[
            ParsedLine(
                line_no=1,
                item_name="Amul Pure Ghee 500ml",
                quantity=1,
                unit_price=Decimal("3149.00"),
                amount=Decimal("3149.00"),
                confidence=0.94,
                readable=True,
                raw_text="Amul Pure Ghee 500ml 1unit  3149",
            )
        ],
        subtotal=Decimal("149.00"),
        delivery_fee=Decimal("0.00"),
        total=Decimal("149.00"),
        vendor="Blinkit",
    )

    scr_149 = DeliveryScreeningService.screen(parsed_149, "TG-TEST3149")
    assert scr_149.totals_match is True
    assert scr_149.lines[0].amount == Decimal("149.00")
    assert scr_149.computed_total == Decimal("149.00")
    assert scr_149.overall == ScreeningVerdict.ALLOW


def test_strikethrough_mrp_pair_swapping_in_screening():
    """
    Verifies that if an extraction picked the higher strikethrough MRP instead of
    discounted selling price, screening arithmetic heals it using the discounted price.
    """
    from backend.app.services.delivery_screening_service import DeliveryScreeningService
    from backend.app.services.invoice_reader import ParsedInvoice, ParsedLine

    # Line where MRP 455 was mistakenly stored in amount, but paid selling price was 43
    parsed = ParsedInvoice(
        lines=[
            ParsedLine(
                line_no=1,
                item_name="Rajdhani Dalia",
                quantity=1,
                unit_price=Decimal("455.00"),
                amount=Decimal("455.00"),
                confidence=0.90,
                readable=True,
                raw_text="Rajdhani Dalia 500g 1unit  455  43",
            )
        ],
        subtotal=Decimal("43.00"),
        delivery_fee=Decimal("0.00"),
        total=Decimal("43.00"),
        vendor="Blinkit",
    )

    scr = DeliveryScreeningService.screen(parsed, "TG-TESTMRP")
    assert scr.totals_match is True
    assert scr.lines[0].amount == Decimal("43.00")
    assert scr.computed_total == Decimal("43.00")
    assert scr.overall == ScreeningVerdict.ALLOW


def test_track_b_reconciler_phantom_3_repair():
    """
    Verifies Track B InvoiceReconciler strips phantom '3' (e.g. 3149 -> 149)
    from line items or grand total to achieve complete reconciliation.
    """
    from research_track.track_b.src.reconciliation import InvoiceReconciler, ReconciliationStatus

    reconciler = InvoiceReconciler()
    invoice_payload = {
        "document_id": "INV-PHANTOM-3-TEST",
        "supplier_name": "Quick Commerce Blinkit",
        "invoice_number": "INV-2026-3149",
        "invoice_date": "2026-11-18",
        "line_items": [
            {
                "line_item_id": "line-1",
                "description": "Tata Tea Gold 250g",
                "quantity": "1",
                "unit_price": "180.00",
                "line_total": "3180.00",  # Misread with phantom leading 3
            }
        ],
        "totals": {
            "subtotal": "180.00",
            "grand_total": "180.00",
        }
    }
    report = reconciler.reconcile(invoice_payload, schema_valid=True)
    assert report.status in (ReconciliationStatus.RECONCILED, ReconciliationStatus.RECONCILED_WITH_WARNINGS)
    assert report.critical_count == 0
    assert report.error_count == 0
    assert invoice_payload["line_items"][0]["line_total"] == "180.00"


def test_cvs_acs_screener_loads_45000_deliverables():
    """
    Verifies that CVSACSScreener defaults to the 45,000 deliverables CSV
    and matches expanded franchise items like La Pino'z.
    """
    from backend.app.services.cvs_acs_screener import cvs_acs_screener

    assert "45000" in str(cvs_acs_screener.csv_path)
    assert len(cvs_acs_screener.exact_map) > 20000

    # Match franchise item from 45000 master list
    res = cvs_acs_screener.screen_item("La Pino'z Giant Slice")
    assert res["matched_from_list"] is True
    assert res["verdict"] == "ALLOW"
    assert res["canonical_root"] == "giant slice"



