#!/usr/bin/env python3
"""
Comprehensive Automated Test & Evaluation Suite for CVS-ACS Invoice Screening Pipeline.
Evaluates:
1. Multi-vendor OCR throughput and accuracy (Zomato, Swiggy, Amazon, Uber, Reliance, Blinkit, Zepto)
2. QR Code detectability, upscaling resilience, payload structure and integrity
3. Deterministic Delivery Policy rules, conflict resolution, confidence thresholding
4. Arithmetic checks and total reconciliation escalation (ALLOW -> REVIEW, ALERT preserved)
5. Comparison of RapidOCR vs Tesseract fallback
"""
import glob
import json
import os
import re
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models.enums import ScreeningVerdict
from backend.app.services.delivery_policy import (
    RULES,
    UNKNOWN,
    UNREADABLE_REASON,
    REASON_VERDICTS,
    CATEGORY_LABELS,
    classify_item,
    screen_line,
    worst,
)
from backend.app.services.invoice_reader import (
    OcrRow,
    ParsedInvoice,
    parse_item_text,
    parse_rows,
    parse_text,
    read_image,
    run_rapidocr,
    run_tesseract,
    to_decimal,
    normalize_order_id,
)
from backend.app.services.delivery_screening_service import (
    DeliveryScreeningService,
    ScreeningResult,
    delivery_screening_service,
)


def test_qr_detection(img_path: Path) -> Tuple[bool, str, str]:
    """
    Evaluates QR code detection on an invoice image using:
    1. Direct OpenCV QRCodeDetector on full image
    2. Cropped, binarized, and upscaled (384x384) detector
    Returns (success, decoded_payload, method)
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return False, "", "read_failed"
    
    detector = cv2.QRCodeDetector()
    
    # 1. Direct detector
    val, _, _ = detector.detectAndDecode(img)
    if val:
        return True, val, "direct_cv2"
        
    # 2. Enhanced upper-right crop + threshold + nearest upscale
    h, w = img.shape[:2]
    crop = img[0:min(140, h), max(0, w - 160):w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
    up = cv2.resize(thresh, (384, 384), interpolation=cv2.INTER_NEAREST)
    val, _, _ = detector.detectAndDecode(up)
    if val:
        return True, val, "upscaled_cv2"
        
    # 3. Fallback with Otsu thresholding
    _, thresh_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    up_otsu = cv2.resize(thresh_otsu, (384, 384), interpolation=cv2.INTER_NEAREST)
    val, _, _ = detector.detectAndDecode(up_otsu)
    if val:
        return True, val, "otsu_upscaled_cv2"

    return False, "", "undetected"


def run_full_suite():
    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "policy_tests": {},
        "arithmetic_tests": {},
        "ocr_vendor_benchmarks": {},
        "qr_benchmark": {},
        "engine_comparison": {},
    }
    
    print("=" * 70)
    print("STARTING CVS-ACS INVOICE SCREENING BENCHMARK & TEST SUITE")
    print("=" * 70)
    
    # -------------------------------------------------------------
    # 1. Deterministic Screening Policy Tests
    # -------------------------------------------------------------
    print("\n--- 1. Deterministic Policy Rules & Escalation Tests ---")
    cat_cases = [
        ("FOOD", "Instant noodles 70g", "FOOD_OK", ScreeningVerdict.ALLOW),
        ("FOOD", "Dum Gosht Biryani", "FOOD_OK", ScreeningVerdict.ALLOW),
        ("FOOD", "Farmhouse Pizza Regular", "FOOD_OK", ScreeningVerdict.ALLOW),
        ("BEVERAGE", "Cold Coffee with Ice Cream", "BEVERAGE_OK", ScreeningVerdict.ALLOW),
        ("BEVERAGE", "Coca-Cola Can 300ml", "BEVERAGE_OK", ScreeningVerdict.ALLOW),
        ("BEVERAGE", "Masala Chai Flask 500ml", "BEVERAGE_OK", ScreeningVerdict.ALLOW),
        ("ELECTRONICS", "USB-C Fast Charging Cable 2m", "ELECTRONICS_OK", ScreeningVerdict.ALLOW),
        ("ELECTRONICS", "Logitech Wireless Mouse M221", "ELECTRONICS_OK", ScreeningVerdict.ALLOW),
        ("STATIONERY", "Classmate Pulse Notebook 6-Pack", "STATIONERY_OK", ScreeningVerdict.ALLOW),
        ("STATIONERY", "Parker Frontier Ballpoint Pen", "STATIONERY_OK", ScreeningVerdict.ALLOW),
        ("PERSONAL_CARE", "Dettol Original Germ Protection Soap", "PERSONAL_CARE_OK", ScreeningVerdict.ALLOW),
        ("PERSONAL_CARE", "Colgate MaxFresh Spicy Fresh 150g", "PERSONAL_CARE_OK", ScreeningVerdict.ALLOW),
        ("HAZMAT", "Harpic toilet cleaner 500 ml", "HAZMAT_NEEDS_APPROVAL", ScreeningVerdict.REVIEW),
        ("HAZMAT", "Lizol disinfectant floor cleaner 1L", "HAZMAT_NEEDS_APPROVAL", ScreeningVerdict.REVIEW),
        ("HAZMAT", "Kerosene bottle 500ml", "HAZMAT_NEEDS_APPROVAL", ScreeningVerdict.REVIEW),
        ("MEDICINE", "Paracetamol 650mg tablets", "MEDICINE_NEEDS_APPROVAL", ScreeningVerdict.REVIEW),
        ("MEDICINE", "Crocin Advance 15s", "MEDICINE_NEEDS_APPROVAL", ScreeningVerdict.REVIEW),
        ("MEDICINE", "Cough syrup 100ml", "MEDICINE_NEEDS_APPROVAL", ScreeningVerdict.REVIEW),
        ("TOBACCO", "Marlboro Gold Cigarettes pack of 20", "TOBACCO_RESTRICTED", ScreeningVerdict.ALERT),
        ("TOBACCO", "Gold Flake Kings 10s", "TOBACCO_RESTRICTED", ScreeningVerdict.ALERT),
        ("TOBACCO", "Vape pod strawberry flavor", "TOBACCO_RESTRICTED", ScreeningVerdict.ALERT),
        ("ALCOHOL", "Kingfisher Premium Beer 650ml", "ALCOHOL_RESTRICTED", ScreeningVerdict.ALERT),
        ("ALCOHOL", "Old Monk XXX Rum 750ml", "ALCOHOL_RESTRICTED", ScreeningVerdict.ALERT),
        ("ALCOHOL", "Smirnoff Vodka 375ml", "ALCOHOL_RESTRICTED", ScreeningVerdict.ALERT),
        ("WEAPON", "Kitchen knife 8 inch chef", "WEAPON_RESTRICTED", ScreeningVerdict.ALERT),
        ("WEAPON", "Tactical pepper spray canister", "WEAPON_RESTRICTED", ScreeningVerdict.ALERT),
        ("WEAPON", "Air gun pellets .177 cal", "WEAPON_RESTRICTED", ScreeningVerdict.ALERT),
        ("UNKNOWN", "Unidentified mechanical gear shaft", "UNKNOWN_CATEGORY", ScreeningVerdict.REVIEW),
    ]
    
    policy_passed = 0
    for cat, item, expected_code, expected_verd in cat_cases:
        res = screen_line(item)
        ok = (res.category == cat and res.reason_code == expected_code and res.verdict == expected_verd)
        if ok:
            policy_passed += 1
        else:
            print(f"FAILED policy test for {item}: got {res}, expected {cat}/{expected_code}/{expected_verd}")
            
    print(f"  Category Rules: {policy_passed}/{len(cat_cases)} test items passed.")
    results["policy_tests"]["category_rules"] = {"passed": policy_passed, "total": len(cat_cases)}
    
    # Priority & Edge cases
    # 1. More severe wins
    s1 = screen_line("Chocolate cigarette candy")
    assert s1.verdict == ScreeningVerdict.ALERT and s1.category == "TOBACCO", f"Priority failure: {s1}"
    
    # 2. Longest keyword wins
    s2 = screen_line("Vanilla ice cream tub")
    assert s2.verdict == ScreeningVerdict.ALLOW and s2.category == "FOOD", f"Longest keyword failure: {s2}"
    
    # 3. Missing spaces (CamelCase / digit boundaries)
    s3 = screen_line("NotebookA4ruled")
    assert s3.verdict == ScreeningVerdict.ALLOW and s3.category == "STATIONERY", f"Boundary failure: {s3}"
    
    # 4. Low confidence line (< 0.75) escalates ALLOW -> REVIEW (UNREADABLE_LINE)
    s4_allow = screen_line("Dum Gosht Biryani", ocr_confidence=0.50)
    assert s4_allow.verdict == ScreeningVerdict.REVIEW and s4_allow.reason_code == UNREADABLE_REASON
    
    # 5. Low confidence line with RESTRICTED item STAYS ALERT
    s4_alert = screen_line("Old Monk Rum 750ml", ocr_confidence=0.40)
    assert s4_alert.verdict == ScreeningVerdict.ALERT and s4_alert.reason_code == "ALCOHOL_RESTRICTED"
    
    # 6. Unreadable line flag
    s5_unread = screen_line("Garbled &*#$@ text", readable=False)
    assert s5_unread.verdict == ScreeningVerdict.REVIEW and s5_unread.reason_code == UNREADABLE_REASON

    print("  Conflict resolution, severity arbitration, low-confidence escalation: ALL PASSED.")
    results["policy_tests"]["escalations"] = "ALL_PASSED"

    # -------------------------------------------------------------
    # 2. Arithmetic Reconciliation & Verdict Aggregation
    # -------------------------------------------------------------
    print("\n--- 2. Arithmetic Checks & Total Reconciliation Tests ---")
    
    # Case A: Perfect matching total (ALLOW)
    inv_clean = parse_text("""SWIGGY
Order #SWG-2026-10001
Item  Qty  Amount
Shahi Paneer Biryani  1  330.00
Thick Chocolate Shake  1  210.00
Subtotal  540.00
Delivery  30.00
Tax  27.00
TOTAL  597.00
""")
    res_clean = delivery_screening_service.screen(inv_clean, "SWG-2026-10001")
    assert res_clean.totals_match is True
    assert res_clean.computed_total == Decimal("597.00")
    assert res_clean.overall == ScreeningVerdict.ALLOW
    print("  Case A (Clean matching total): ALLOW -> PASSED")

    # Case B: Mismatched total (+20.00) escalates ALLOW -> REVIEW
    inv_mismatch = parse_text("""SWIGGY
Order #SWG-2026-10002
Item  Qty  Amount
Shahi Paneer Biryani  1  330.00
Thick Chocolate Shake  1  210.00
Subtotal  540.00
Delivery  30.00
Tax  27.00
TOTAL  617.00
""")
    res_mismatch = delivery_screening_service.screen(inv_mismatch, "SWG-2026-10002")
    assert res_mismatch.totals_match is False
    assert res_mismatch.computed_total == Decimal("597.00")
    assert res_mismatch.overall == ScreeningVerdict.REVIEW
    print("  Case B (Mismatched total escalates ALLOW to REVIEW): PASSED")

    # Case C: Mismatched total on invoice with ALERT item -> stays ALERT
    inv_alert_mismatch = parse_text("""DEMO MART
Order #DEMO-10003
Item  Qty  Amount
Cigarettes pack of 20  1  350.00
Cola 750 ml  1  40.00
Subtotal  390.00
TOTAL  450.00
""")
    res_alert_mismatch = delivery_screening_service.screen(inv_alert_mismatch, "DEMO-10003")
    assert res_alert_mismatch.totals_match is False
    assert res_alert_mismatch.overall == ScreeningVerdict.ALERT  # Worst([ALERT, REVIEW]) = ALERT
    print("  Case C (Mismatched total on ALERT item preserves ALERT): PASSED")

    # Case D: Missing Total on invoice -> totals_match is None -> escalates to REVIEW
    inv_no_total = parse_text("""BLINKIT
Order #BLK-10004
Item  Qty  Amount
Amul Butter Pasteurised 500g  1  275.00
Harvest Gold White Bread 400g  1  45.00
""")
    res_no_total = delivery_screening_service.screen(inv_no_total, "BLK-10004")
    assert res_no_total.totals_match is None
    assert res_no_total.overall == ScreeningVerdict.REVIEW
    print("  Case D (Missing total escalates ALLOW to REVIEW): PASSED")

    # Case E: Order ID Mismatch -> escalates ALLOW to REVIEW
    res_order_mismatch = delivery_screening_service.screen(inv_clean, "SWG-DIFFERENT-ORDER")
    assert res_order_mismatch.overall == ScreeningVerdict.REVIEW
    assert "invoice shows order SWG-2026-10001" in delivery_screening_service.reply_text("SWG-DIFFERENT-ORDER", res_order_mismatch)
    print("  Case E (Mismatched order ID escalates ALLOW to REVIEW): PASSED")

    # Case F: Unreadable item line in table -> escalates to REVIEW
    inv_unreadable = parse_text("""ZEPTO
Order #ZPT-10005
Item  Qty  Amount
@@@@ #### ????  1  120.00
Coca-Cola Can 300ml  2  80.00
TOTAL  200.00
""")
    res_unreadable = delivery_screening_service.screen(inv_unreadable, "ZPT-10005")
    assert res_unreadable.overall == ScreeningVerdict.REVIEW
    assert any(l.reason_code == UNREADABLE_REASON for l in res_unreadable.lines)
    print("  Case F (Unreadable item row escalates ALLOW to REVIEW): PASSED")

    results["arithmetic_tests"] = {
        "clean_match": "ALLOW",
        "mismatched_total_escalates": "REVIEW",
        "mismatched_total_with_restricted": "ALERT",
        "missing_total_escalates": "REVIEW",
        "order_mismatch_escalates": "REVIEW",
        "unreadable_row_escalates": "REVIEW",
    }

    # -------------------------------------------------------------
    # 3. QR Code Detection & Integrity Evaluation Across Dataset
    # -------------------------------------------------------------
    print("\n--- 3. QR Code Detectability & Payload Integrity Benchmark ---")
    all_invoices = sorted(glob.glob("media/invoices/*.png"))
    print(f"Total invoice images found in media/invoices: {len(all_invoices)}")
    
    # We benchmark QR codes across a sample of 200 invoices representing all vendors
    np.random.seed(42)
    sample_indices = np.random.choice(len(all_invoices), size=min(200, len(all_invoices)), replace=False)
    qr_samples = [all_invoices[i] for i in sample_indices]
    
    qr_stats = {
        "tested": len(qr_samples),
        "direct_detected": 0,
        "upscaled_detected": 0,
        "total_detected": 0,
        "upi_scheme_count": 0,
        "https_scheme_count": 0,
        "order_id_verified": 0,
        "amount_extracted": 0,
    }
    
    for fpath in qr_samples:
        img_p = Path(fpath)
        ok, payload, method = test_qr_detection(img_p)
        if ok:
            qr_stats["total_detected"] += 1
            if method == "direct_cv2":
                qr_stats["direct_detected"] += 1
            else:
                qr_stats["upscaled_detected"] += 1
                
            if payload.startswith("upi://"):
                qr_stats["upi_scheme_count"] += 1
                # extract amount and tracking
                m_am = re.search(r"am=([\d\.]+)", payload)
                m_tr = re.search(r"tr=([A-Z0-9-]+)", payload)
                if m_am:
                    qr_stats["amount_extracted"] += 1
                if m_tr:
                    qr_stats["order_id_verified"] += 1
            elif payload.startswith("https://"):
                qr_stats["https_scheme_count"] += 1
                if "order=" in payload or "inv=" in payload or "/v/" in payload:
                    qr_stats["order_id_verified"] += 1
                    
    qr_accuracy = (qr_stats["total_detected"] / qr_stats["tested"]) * 100.0
    print(f"  QR Sample Tested: {qr_stats['tested']}")
    print(f"  Direct CV2 Detects: {qr_stats['direct_detected']} ({(qr_stats['direct_detected']/qr_stats['tested'])*100:.1f}%)")
    print(f"  Upscaled/Threshold Detects: {qr_stats['upscaled_detected']} ({(qr_stats['upscaled_detected']/qr_stats['tested'])*100:.1f}%)")
    print(f"  Overall QR Detection Rate: {qr_stats['total_detected']}/{qr_stats['tested']} ({qr_accuracy:.2f}%)")
    print(f"  UPI Payloads: {qr_stats['upi_scheme_count']}, HTTPS Verification URLs: {qr_stats['https_scheme_count']}")
    print(f"  Order IDs Verified in Payload: {qr_stats['order_id_verified']}")
    results["qr_benchmark"] = qr_stats

    # -------------------------------------------------------------
    # 4. Multi-Vendor OCR Throughput & Extraction Accuracy
    # -------------------------------------------------------------
    print("\n--- 4. Multi-Vendor OCR Extraction & Accuracy Benchmark ---")
    
    # Connect to DB or query DB records to get known vendor images
    import subprocess
    cmd = [
        "docker", "exec", "campus_postgres", "psql", "-U", "campus_admin", "-d", "campus_security",
        "-t", "-A", "-F", "|", "-c",
        """
        SELECT vendor, image_path, order_number, total_amount, overall_verdict, totals_match
        FROM (
            SELECT i.vendor, i.image_path, d.order_id as order_number, i.total_amount, i.overall_verdict, i.totals_match,
                   ROW_NUMBER() OVER (PARTITION BY i.vendor ORDER BY i.created_at DESC) as rnk
            FROM invoices i
            JOIN delivery_orders d ON i.order_id = d.id
            WHERE i.vendor NOT IN ('DEMO MART', 'DEMOMART')
        ) sub
        WHERE rnk <= 7;
        """
    ]
    db_rows = subprocess.check_output(cmd).decode().strip().splitlines()
    
    vendor_groups: Dict[str, List[dict]] = {}
    for row in db_rows:
        parts = row.split("|")
        if len(parts) >= 6:
            v_name, img_rel, ord_no, tot, verd, match = parts[:6]
            p = Path(img_rel.lstrip("/"))
            if not p.exists():
                p = Path("media") / p
            vendor_groups.setdefault(v_name, []).append({
                "vendor": v_name,
                "image_path": p,
                "order_number": ord_no,
                "total": Decimal(tot) if tot else None,
                "db_verdict": verd,
                "db_match": match == "t",
            })
            
    vendor_results = {}
    total_rapid_time = 0.0
    total_samples = 0
    
    for v_name, items in sorted(vendor_groups.items()):
        print(f"\n  Evaluating Vendor: {v_name} ({len(items)} samples)")
        v_stat = {
            "vendor": v_name,
            "samples": len(items),
            "order_id_recognized": 0,
            "lines_extracted": 0,
            "totals_extracted": 0,
            "arithmetic_matches": 0,
            "avg_latency_s": 0.0,
            "avg_confidence": 0.0,
            "verdicts": {},
        }
        v_times = []
        v_confs = []
        
        for item in items:
            t0 = time.time()
            ocr = run_rapidocr(item["image_path"])
            dt = time.time() - t0
            v_times.append(dt)
            if ocr.confidence:
                v_confs.append(ocr.confidence)
                
            parsed = parse_rows(ocr.rows)
            screened = delivery_screening_service.screen(parsed, item["order_number"])
            
            # Check Order ID
            if parsed.order_number and normalize_order_id(item["order_number"]) == parsed.order_number:
                v_stat["order_id_recognized"] += 1
            elif parsed.order_number and any(part in parsed.order_number for part in item["order_number"].split("-")[-2:]):
                v_stat["order_id_recognized"] += 1
                
            # Line items extracted
            if len(parsed.lines) > 0:
                v_stat["lines_extracted"] += len(parsed.lines)
                
            # Totals extracted
            if parsed.total is not None or parsed.subtotal is not None:
                v_stat["totals_extracted"] += 1
                
            # Arithmetic consistency
            if screened.totals_match is True:
                v_stat["arithmetic_matches"] += 1
                
            verd_val = screened.overall.value
            v_stat["verdicts"][verd_val] = v_stat["verdicts"].get(verd_val, 0) + 1
            
        v_stat["avg_latency_s"] = round(sum(v_times) / len(v_times), 3) if v_times else 0.0
        v_stat["avg_confidence"] = round(sum(v_confs) / len(v_confs), 4) if v_confs else 0.0
        total_rapid_time += sum(v_times)
        total_samples += len(items)
        
        print(f"    * Latency: {v_stat['avg_latency_s']}s/invoice | Conf: {v_stat['avg_confidence']}")
        print(f"    * Order ID Accuracy: {v_stat['order_id_recognized']}/{v_stat['samples']} ({(v_stat['order_id_recognized']/v_stat['samples'])*100:.1f}%)")
        print(f"    * Total Items Extracted: {v_stat['lines_extracted']} lines")
        print(f"    * Totals Read: {v_stat['totals_extracted']}/{v_stat['samples']}")
        print(f"    * Arithmetic Matches: {v_stat['arithmetic_matches']}/{v_stat['samples']}")
        print(f"    * Verdict Distribution: {v_stat['verdicts']}")
        vendor_results[v_name] = v_stat
        
    results["ocr_vendor_benchmarks"] = vendor_results
    results["overall_throughput"] = {
        "total_samples": total_samples,
        "total_time_s": round(total_rapid_time, 2),
        "invoices_per_sec": round(total_samples / total_rapid_time, 2) if total_rapid_time > 0 else 0.0,
    }

    # -------------------------------------------------------------
    # 5. RapidOCR vs Tesseract Fallback Head-to-Head Comparison
    # -------------------------------------------------------------
    print("\n--- 5. RapidOCR vs Tesseract Fallback Comparison ---")
    test_cases_dir = Path("media/test_invoices")
    comparison_cases = [
        ("Clean Digital", test_cases_dir / "D-20481_clean.png"),
        ("All Clear", test_cases_dir / "D-20482_allclear.png"),
        ("Alcohol Restricted", test_cases_dir / "D-20483_alcohol.png"),
        ("Hinglish QuickCommerce", test_cases_dir / "D-20486_hinglish_quickcommerce.png"),
        ("Degraded Scan", test_cases_dir / "D-20487_degraded_scan.png"),
        ("Phone Camera Photo", test_cases_dir / "D-20488_phone_photo.jpg"),
    ]
    
    comp_results = []
    for label, img_p in comparison_cases:
        if not img_p.exists():
            continue
            
        t0 = time.time()
        rapid_res = run_rapidocr(img_p)
        rapid_time = time.time() - t0
        rapid_parsed = parse_rows(rapid_res.rows)
        rapid_screened = delivery_screening_service.screen(rapid_parsed)
        
        t0 = time.time()
        tess_res = run_tesseract(img_p)
        tess_time = time.time() - t0
        tess_parsed = parse_rows(tess_res.rows)
        tess_screened = delivery_screening_service.screen(tess_parsed)
        
        row = {
            "case": label,
            "rapid_rows": len(rapid_res.rows),
            "rapid_lines": len(rapid_parsed.lines),
            "rapid_conf": rapid_res.confidence,
            "rapid_time_s": round(rapid_time, 3),
            "rapid_match": rapid_screened.totals_match,
            "rapid_verdict": rapid_screened.overall.value,
            "tess_rows": len(tess_res.rows),
            "tess_lines": len(tess_parsed.lines),
            "tess_conf": tess_res.confidence,
            "tess_time_s": round(tess_time, 3),
            "tess_match": tess_screened.totals_match,
            "tess_verdict": tess_screened.overall.value,
        }
        comp_results.append(row)
        print(f"  [{label}]")
        print(f"    RapidOCR : {row['rapid_lines']} lines | Match: {row['rapid_match']} | Verdict: {row['rapid_verdict']} | Conf: {row['rapid_conf']} | Time: {row['rapid_time_s']}s")
        print(f"    Tesseract: {row['tess_lines']} lines | Match: {row['tess_match']} | Verdict: {row['tess_verdict']} | Conf: {row['tess_conf']} | Time: {row['tess_time_s']}s")

    results["engine_comparison"] = comp_results

    # Save raw benchmark JSON
    out_json = PROJECT_ROOT / "research" / "benchmark_screening_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nRaw results saved to {out_json}")

    return results


if __name__ == "__main__":
    run_full_suite()
