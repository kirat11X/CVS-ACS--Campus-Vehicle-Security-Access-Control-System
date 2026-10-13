# Track B: Test Case Matrix & Evaluation Fixture Documentation

This document specifies the complete test matrix for evaluating invoice extraction and deterministic reconciliation across 32 synthetic invoices (`fixtures/synthetic_invoices.json`) and 6 adversarial test cases (`fixtures/adversarial_cases.json`).

---

## 1. Test Suite Overview

| Category | Count | Focus Areas | Expected Reconciliation Status |
| :--- | :--- | :--- | :--- |
| **Standard Clean Invoices** | 5 | Single-line, multi-line (2-6 items), standard headers | `RECONCILED` |
| **Missing Metadata Edge Cases** | 3 | Missing invoice number, missing supplier, missing date | `RECONCILED_WITH_WARNINGS` |
| **Multi-Currency** | 3 | USD ($), EUR (€), GBP (£) with proper symbol mapping | `RECONCILED` |
| **Tax Structures** | 3 | Tax-inclusive (0% extra), tax-exclusive (GST 5-18%), multi-rate | `RECONCILED` / `RECONCILED_WITH_WARNINGS` |
| **Discounts & Logistics Fees** | 3 | Item discounts, invoice coupons, delivery & convenience fees | `RECONCILED` |
| **Formatting Variations** | 3 | Decimal rounding (1-cent drift), European commas, wrapped text | `RECONCILED` |
| **Edge Cases & Returns** | 3 | Duplicate descriptions, negative quantities (credits), free items | `RECONCILED` / `RECONCILED_WITH_WARNINGS` |
| **Arithmetic Failures** | 4 | Line multiplication mismatch, subtotal sum error, missing total | `DISCREPANCY_FLAGGED` / `CRITICAL_ARITHMETIC_FAILURE` |
| **Multi-Page & Disambiguation**| 5 | Multi-page tables, Day-First dates, duplicate invoice numbers | `RECONCILED` |
| **Adversarial / Malicious** | 6 | Total spoofing, ghost items, malformed JSON, schema violations | `DISCREPANCY_FLAGGED` / `SCHEMA_VALIDATION_ERROR` |
| **Total Test Corpus** | **38** | Complete coverage of financial parsing and security checks | Full spectrum |

---

## 2. Synthetic Test Case Matrix (32 Fixtures)

| ID | Category | Key Input Features | Expected Validation Findings | Expected Status | Human Review? | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **INV-SYN-001** | `single_line` | 1 item (Amul Butter), ₹275.00 | None | `RECONCILED` | No | Baseline single-item quick-commerce order. |
| **INV-SYN-002** | `multi_line` | 4 grocery items, ₹450.00 | None | `RECONCILED` | No | Multi-line table with clean column alignment. |
| **INV-SYN-003** | `multi_line_large` | 6 stationery items, ₹1,960.00 | None | `RECONCILED` | No | Large order with notebooks, pens, reams. |
| **INV-SYN-004** | `missing_invoice_number` | No invoice number label | `VAL_MISSING_MANDATORY_FIELD` (WARNING) | `RECONCILED_WITH_WARNINGS` | Yes | Audit warning logged; totals still balance. |
| **INV-SYN-005** | `missing_supplier` | No vendor or supplier name | `VAL_MISSING_MANDATORY_FIELD` (WARNING) | `RECONCILED_WITH_WARNINGS` | Yes | Vendor absent; requires guard check. |
| **INV-SYN-006** | `missing_date` | No invoice date | `VAL_MISSING_MANDATORY_FIELD` (WARNING) | `RECONCILED_WITH_WARNINGS` | Yes | Date absent; requires timestamp audit. |
| **INV-SYN-007** | `currency_usd` | $ symbol, USD 64.00 | None | `RECONCILED` | No | Foreign currency parsing without assumption. |
| **INV-SYN-008** | `currency_eur` | € symbol, EUR 81.00 | None | `RECONCILED` | No | European currency code standard. |
| **INV-SYN-009** | `currency_gbp` | £ symbol, GBP 100.00 | None | `RECONCILED` | No | British Pound currency standard. |
| **INV-SYN-010** | `tax_inclusive` | Tax stated as 0.00 or included | None | `RECONCILED` | No | Pharmacy MRP inclusive tax model. |
| **INV-SYN-011** | `tax_exclusive` | Subtotal 500, Tax 90, Total 590 | None | `RECONCILED` | No | Standard GST 18% tax addition. |
| **INV-SYN-012** | `tax_multiple_rates` | Subtotal 1000, Tax 128, Total 1128 | None | `RECONCILED` | No | Split tax rates across grocery and hardware. |
| **INV-SYN-013** | `discount_item_level` | Subtotal 300, Discount 30, Total 270 | None | `RECONCILED` | No | Item discount properly subtracted. |
| **INV-SYN-014** | `discount_invoice_level` | Subtotal 850, Promo 100, Total 750 | None | `RECONCILED` | No | Global invoice promo code coupon deduction. |
| **INV-SYN-015** | `shipping_delivery_fee`| Subtotal 330, Delivery 40, Total 370 | None | `RECONCILED` | No | Logistics and platform fees added to total. |
| **INV-SYN-016** | `rounding_diff` | 3 x 33.33 = 99.99, Tax 5.00, Total 105.00 | `VAL_SUSPICIOUS_ROUNDING` (INFO) | `RECONCILED_WITH_WARNINGS` | No | Legitimate 0.01 commercial round-off. |
| **INV-SYN-017** | `comma_decimal` | European decimals (10,50 & 21,00) | None | `RECONCILED` | No | Locale-aware comma parsing. |
| **INV-SYN-018** | `duplicate_descriptions`| Two rows: 'A4 Paper Ream' | `VAL_DUPLICATE_ITEM_DESCRIPTION` (INFO) | `RECONCILED` | No | Multiple lines with identical descriptions. |
| **INV-SYN-019** | `wrapped_descriptions`| Description wrapped across 2 lines | None | `RECONCILED` | No | Concatenation of continuation line text. |
| **INV-SYN-020** | `negative_quantity` | Office Chair (2) + Return Lamp (-1) | `VAL_NEGATIVE_QUANTITY` (WARNING) | `RECONCILED_WITH_WARNINGS` | Yes | Credit note / return item verification. |
| **INV-SYN-021** | `arithmetic_line_err` | 2 x 50.00 reported as 120.00 | `VAL_LINE_ARITHMETIC_MISMATCH` (ERROR) | `DISCREPANCY_FLAGGED` | Yes | Line math is mathematically corrupt. |
| **INV-SYN-022** | `arithmetic_total_err` | Line sum is 100.00, subtotal is 150.00 | `VAL_SUBTOTAL_MISMATCH` (ERROR) | `DISCREPANCY_FLAGGED` | Yes | Line sum fails to match subtotal. |
| **INV-SYN-023** | `missing_unit_price` | Qty 2, Total 400.00, Unit price blank | `VAL_MISSING_MANDATORY_FIELD` (INFO) | `RECONCILED` | No | Unit price inferred from line total / qty. |
| **INV-SYN-024** | `unreadable_totals` | Grand total missing/unreadable | `VAL_MISSING_MANDATORY_FIELD` (CRITICAL) | `CRITICAL_ARITHMETIC_FAILURE`| Yes | Cannot establish payable liability. |
| **INV-SYN-025** | `multi_page_invoice` | 6 items across pages 1 and 2 | None | `RECONCILED` | No | Aggregated cross-page line items. |
| **INV-SYN-026** | `ambiguous_date` | Date '04/05/2026' (May 4th) | None | `RECONCILED` | No | Evaluated under DAY_FIRST locale rule. |
| **INV-SYN-027** | `ambiguous_currency`| No currency symbol stated | None | `RECONCILED` | No | Preserves currency as null without guessing. |
| **INV-SYN-028** | `duplicate_inv_num_a`| 'INV-DUPLICATE-99' (Apex Medical) | None | `RECONCILED` | No | Vendor-scoped invoice number disambiguation. |
| **INV-SYN-029** | `duplicate_inv_num_b`| 'INV-DUPLICATE-99' (Book Depot) | None | `RECONCILED` | No | Proves (vendor, invoice_no) composite key. |
| **INV-SYN-030** | `zero_quantity_promo`| Promo item with 0.00 price | None | `RECONCILED` | No | Marketing zero-cost free sample handling. |
| **INV-SYN-031** | `partial_payment` | Paid 2000.00, Due 1500.00 on 3500.00 | None | `RECONCILED` | No | Payment reconciliation checks balance due. |
| **INV-SYN-032** | `quick_commerce_bill`| Delivery fee, packing, discount, roundoff | None | `RECONCILED` | No | Complex modern Indian quick delivery bill. |

---

## 3. Adversarial Test Cases (6 Fixtures)

| ID | Adversarial Vector | Expected Failure Reason Code | Expected Severity | Reconciliation Status | Security Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ADV-001** | Total Spoofing (Items sum 400, Total claims 500) | `VAL_SUBTOTAL_MISMATCH` | `ERROR` | `DISCREPANCY_FLAGGED` | Catches fabricated billing totals. |
| **ADV-002** | Tampered Line Arithmetic (5 x 10 = 100) | `VAL_LINE_ARITHMETIC_MISMATCH` | `ERROR` | `DISCREPANCY_FLAGGED` | Catches line-level price inflation. |
| **ADV-003** | Inverted Tax Arithmetic (Tax subtracted -180) | `VAL_GRAND_TOTAL_MISMATCH` | `CRITICAL` | `CRITICAL_ARITHMETIC_FAILURE`| Prevents tax evasion anomalies. |
| **ADV-004** | Ghost Item Omission (3 items in table, 2 in sum)| `VAL_SUBTOTAL_MISMATCH` | `ERROR` | `DISCREPANCY_FLAGGED` | Catches hidden off-book items. |
| **ADV-005** | Malformed Model JSON (Truncated tokens) | `VAL_SCHEMA_VIOLATION` | `CRITICAL` | `SCHEMA_VALIDATION_ERROR` | Rejects unparseable VLM outputs. |
| **ADV-006** | Schema Constraint Violation (Missing line_item_id)| `VAL_SCHEMA_VIOLATION` | `CRITICAL` | `SCHEMA_VALIDATION_ERROR` | Enforces rigid data contracts. |
