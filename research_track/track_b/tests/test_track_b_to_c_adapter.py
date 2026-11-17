"""
Unit Tests for Track B to Track C Cross-Track Adapter (X-S1-001).

Verifies the critical architectural contracts:
1. Exact Decimal Preservation: Lossless numeric conversion avoiding IEEE 754 binary float drift.
2. Missing / Null Quantity Handling: Graceful handling with clear metadata indicators.
3. Default Quantity Option: Configurable fallback quantity with explicit provenance flags.
4. Unit Taxonomy Normalization: Canonical mappings across count, mass, volume, and packaging vocabularies.
5. Full Audit Provenance: Unmodified line_item_id, raw descriptions, document ID, page, and evidence.
6. Platform Resolution: Automatic inference from vendor names and manual overrides.
7. Decoupled Architecture: Zero policy engine or rule imports in the adapter.
8. End-to-End Invoice Processing: Complete invoice dictionary conversion to screening payloads.
"""

from decimal import Decimal
import sys
import unittest

from research_track.adapters.track_b_to_c import (
    CANONICAL_UNIT_MAP_LOWER,
    CANONICAL_UNIT_MAP_UPPER,
    ScreeningInputPayload,
    ScreeningItemInput,
    TrackBToCAdapter,
    convert_invoice_to_screening_payloads,
    convert_line_item_to_screening_input,
    infer_platform_from_vendor,
    normalize_screening_unit,
    parse_exact_decimal_quantity,
)


class TestTrackBToCAdapterContracts(unittest.TestCase):

    def test_lossless_decimal_quantity_preservation(self):
        """
        Verifies exact Decimal preservation without binary IEEE 754 float drift.
        For example, 0.1 in float is 0.10000000000000000555...; as Decimal it is exactly 0.1.
        """
        test_values = [
            ("0.1", Decimal("0.1")),
            ("0.05", Decimal("0.05")),
            ("2.50", Decimal("2.50")),
            ("123.456", Decimal("123.456")),
            (Decimal("42.75"), Decimal("42.75")),
            (10, Decimal("10")),
            (1.5, Decimal("1.5")),
        ]

        for raw_val, expected_dec in test_values:
            parsed = parse_exact_decimal_quantity(raw_val)
            self.assertIsInstance(parsed, Decimal)
            self.assertEqual(parsed, expected_dec)
            self.assertEqual(str(parsed), str(expected_dec))

        # Test within adapted line item
        item = {
            "line_item_id": "line-exact-01",
            "description": "Chemical Reagent A",
            "quantity": "0.10",
            "unit": "ltr",
        }
        adapted = convert_line_item_to_screening_input(item)
        self.assertIsInstance(adapted.quantity, Decimal)
        self.assertEqual(adapted.quantity, Decimal("0.10"))
        # Ensure serialization keeps exact Decimal value
        serialized = adapted.to_dict()
        self.assertEqual(serialized["quantity"], Decimal("0.10"))

    def test_missing_quantity_graceful_handling(self):
        """
        When quantity is missing (None), the adapter must preserve None (never coerce to 0 or 1),
        and flag metadata with explicit provenance indicators.
        """
        item = {
            "line_item_id": "item-service-01",
            "description": "Standard Delivery Fee",
            "quantity": None,
            "unit": None,
        }
        adapted = convert_line_item_to_screening_input(item)

        self.assertIsNone(adapted.quantity)
        self.assertTrue(adapted.metadata.get("is_quantity_missing"))
        self.assertEqual(adapted.metadata.get("quantity_indicator"), "MISSING")
        self.assertFalse(adapted.metadata.get("quantity_defaulted", False))

    def test_default_quantity_option(self):
        """
        When default_quantity is configured, missing quantities should adopt the default
        while clearly marking quantity_defaulted=True in metadata.
        """
        item = {
            "line_item_id": "item-snack-01",
            "description": "Fresh Bakery Muffin",
            "quantity": None,
            "unit": "pcs",
        }
        adapted = convert_line_item_to_screening_input(
            item,
            default_quantity=Decimal("1.00"),
        )

        self.assertEqual(adapted.quantity, Decimal("1.00"))
        self.assertFalse(adapted.metadata.get("is_quantity_missing"))
        self.assertEqual(adapted.metadata.get("quantity_indicator"), "DEFAULTED")
        self.assertTrue(adapted.metadata.get("quantity_defaulted"))

    def test_present_quantity_indicator(self):
        """
        When quantity is explicitly provided, verify quantity_indicator is PRESENT.
        """
        item = {
            "line_item_id": "item-01",
            "description": "Apples",
            "quantity": "4",
            "unit": "kg",
        }
        adapted = convert_line_item_to_screening_input(item)
        self.assertEqual(adapted.quantity, Decimal("4"))
        self.assertFalse(adapted.metadata.get("is_quantity_missing"))
        self.assertEqual(adapted.metadata.get("quantity_indicator"), "PRESENT")

    def test_unit_normalization_vocabulary_lowercase(self):
        """
        Verifies normalization into canonical lowercase unit vocabulary
        ('unit', 'kg', 'g', 'pack', 'box', 'bottle', etc.).
        """
        unit_tests = [
            # pieces / count
            ("pcs", "unit"),
            ("pc", "unit"),
            ("pieces", "unit"),
            ("piece", "unit"),
            ("nos", "unit"),
            ("no", "unit"),
            ("no.", "unit"),
            ("unit", "unit"),
            ("units", "unit"),
            ("ea", "unit"),
            ("each", "unit"),
            # mass
            ("kg", "kg"),
            ("kgs", "kg"),
            ("kilogram", "kg"),
            ("kilograms", "kg"),
            ("g", "g"),
            ("gm", "g"),
            ("gms", "g"),
            ("gram", "g"),
            ("grams", "g"),
            ("mg", "mg"),
            ("milligram", "mg"),
            # volume
            ("ltr", "l"),
            ("l", "l"),
            ("liter", "l"),
            ("litres", "l"),
            ("ml", "ml"),
            ("milliliters", "ml"),
            # packaging
            ("pack", "pack"),
            ("packs", "pack"),
            ("pkt", "pack"),
            ("pkts", "pack"),
            ("packet", "pack"),
            ("box", "box"),
            ("boxes", "box"),
            ("bx", "box"),
            ("carton", "box"),
            ("bottle", "bottle"),
            ("bottles", "bottle"),
            ("btl", "bottle"),
            ("can", "can"),
            ("cans", "can"),
            ("strip", "strip"),
            ("strips", "strip"),
            ("dozen", "dozen"),
            ("doz", "dozen"),
            ("bag", "bag"),
            # unrecognized passed through cleanly
            ("custom_roll", "custom_roll"),
            ("", None),
            (None, None),
        ]

        for raw_unit, expected in unit_tests:
            normalized = normalize_screening_unit(raw_unit, lowercase=True)
            self.assertEqual(normalized, expected, f"Failed for raw unit: {raw_unit}")

    def test_unit_normalization_vocabulary_uppercase(self):
        """
        Verifies backward compatibility with uppercase canonical taxonomy.
        """
        self.assertEqual(normalize_screening_unit("litres", lowercase=False), "LTR")
        self.assertEqual(normalize_screening_unit("kgs", lowercase=False), "KG")
        self.assertEqual(normalize_screening_unit("bottles", lowercase=False), "BOTTLE")
        self.assertEqual(normalize_screening_unit("pcs", lowercase=False), "PCS")

    def test_full_provenance_preservation(self):
        """
        Verifies line_item_id, unmodified raw description, normalized description,
        document ID, invoice date, supplier, prices, source page, and bounding box evidence.
        """
        item = {
            "line_item_id": "line-xyz-99",
            "description": "  Raw Unedited Description with Symbols & Co.  ",
            "normalized_description": "Raw Unedited Description with Symbols & Co.",
            "quantity": "3.50",
            "unit": "kgs",
            "unit_price": "120.00",
            "line_total": "420.00",
            "currency": "INR",
            "source_page": 2,
            "evidence": {
                "page": 2,
                "bounding_box": [0.15, 0.25, 0.65, 0.35],
                "raw_text_snippet": "Raw Unedited Description 3.50 kgs 420.00",
            },
        }
        invoice_ctx = {
            "document_id": "DOC-INV-2026-88",
            "invoice_number": "INV/2026/888",
            "supplier_name": "Blinkit Commerce Pvt Ltd",
            "invoice_date": "2026-11-16",
            "currency": "INR",
        }

        adapted = convert_line_item_to_screening_input(item, invoice_context=invoice_ctx, lowercase_unit=True)

        # Invariant checks
        self.assertEqual(adapted.line_item_id, "line-xyz-99")
        self.assertEqual(adapted.raw_item_description, "Raw Unedited Description with Symbols & Co.")
        self.assertEqual(adapted.raw_description, "Raw Unedited Description with Symbols & Co.")
        self.assertEqual(adapted.normalized_description, "Raw Unedited Description with Symbols & Co.")
        self.assertEqual(adapted.quantity, Decimal("3.50"))
        self.assertEqual(adapted.unit, "kg")

        # Provenance metadata
        meta = adapted.metadata
        self.assertEqual(meta["source_document_id"], "DOC-INV-2026-88")
        self.assertEqual(meta["invoice_number"], "INV/2026/888")
        self.assertEqual(meta["supplier_name"], "Blinkit Commerce Pvt Ltd")
        self.assertEqual(meta["invoice_date"], "2026-11-16")
        self.assertEqual(meta["currency"], "INR")
        self.assertEqual(meta["source_page"], 2)
        self.assertEqual(meta["raw_unit"], "kgs")
        self.assertEqual(meta["evidence"]["bounding_box"], [0.15, 0.25, 0.65, 0.35])

    def test_platform_resolution_and_override(self):
        """
        Verifies platform inference from vendor name and explicit override priority.
        """
        self.assertEqual(infer_platform_from_vendor("Zomato Daily Delivery"), "ZOMATO")
        self.assertEqual(infer_platform_from_vendor("Blinkit Commerce Pvt Ltd"), "BLINKIT")
        self.assertEqual(infer_platform_from_vendor("Zepto Quick Commerce"), "ZEPTO")
        self.assertEqual(infer_platform_from_vendor("Swiggy Instamart Superstore"), "SWIGGY_INSTAMART")
        self.assertEqual(infer_platform_from_vendor("Amazon Retail India"), "AMAZON")

        # Inference from supplier name in context
        item = {"description": "Cold Drink", "quantity": "1"}
        adapted_inferred = convert_line_item_to_screening_input(
            item,
            invoice_context={"supplier_name": "Zomato Kitchens"},
        )
        self.assertEqual(adapted_inferred.platform, "ZOMATO")

        # Explicit platform argument overrides supplier inference
        adapted_override = convert_line_item_to_screening_input(
            item,
            platform="CUSTOM_PLATFORM",
            invoice_context={"supplier_name": "Zomato Kitchens"},
        )
        self.assertEqual(adapted_override.platform, "CUSTOM_PLATFORM")

    def test_decoupled_architecture_no_policy_engine_imports(self):
        """
        CRITICAL ARCHITECTURAL CONTRACT:
        track_b_to_c adapter must NOT import DeterministicPolicyEngine, PolicyRule,
        or any screening evaluation logic from Track C.
        """
        import research_track.adapters.track_b_to_c as adapter_module

        # Ensure no policy engine symbols in module namespace
        self.assertFalse(hasattr(adapter_module, "DeterministicPolicyEngine"))
        self.assertFalse(hasattr(adapter_module, "PolicyRule"))
        self.assertFalse(hasattr(adapter_module, "ScreeningResult"))

        # Verify in a clean isolated Python process that importing the adapter
        # does not cause any forbidden policy submodules to be imported.
        import subprocess

        cmd = [
            sys.executable,
            "-c",
            (
                "import sys, research_track.adapters.track_b_to_c; "
                "forbidden = ['research_track.track_c.src.policy_engine', "
                "'research_track.track_c.src.reason_codes', "
                "'research_track.track_c.src.audit_records']; "
                "imported = [m for m in forbidden if m in sys.modules]; "
                "assert not imported, f'Forbidden modules imported: {imported}'; "
                "print('OK')"
            ),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(
            res.returncode,
            0,
            f"Adapter imported forbidden Track C modules: {res.stderr}",
        )

    def test_end_to_end_invoice_conversion(self):
        """
        Converts an entire invoice document with multiple items, platform fees, and metadata.
        """
        invoice_doc = {
            "document_id": "INV-BLINKIT-2026-0042",
            "invoice_number": "BLK/2026/0042",
            "supplier_name": "Blinkit Quick Commerce",
            "invoice_date": "2026-11-16",
            "currency": "INR",
            "line_items": [
                {
                    "line_item_id": "item-1",
                    "description": "Amul Pasteurised Butter 500g",
                    "quantity": "2",
                    "unit": "pack",
                    "unit_price": "275.00",
                    "line_total": "550.00",
                    "source_page": 1,
                },
                {
                    "line_item_id": "item-2",
                    "description": "Coca Cola Can 330ml",
                    "quantity": "6",
                    "unit": "can",
                    "unit_price": "40.00",
                    "line_total": "240.00",
                    "source_page": 1,
                },
                {
                    "line_item_id": "item-3",
                    "description": "Instant Grocery Delivery Fee",
                    "quantity": None,
                    "unit": None,
                    "line_total": "25.00",
                    "source_page": 1,
                },
            ],
            "totals": {
                "subtotal": "790.00",
                "delivery_fee": "25.00",
                "grand_total": "815.00",
            },
        }

        adapter = TrackBToCAdapter()
        payloads = adapter.adapt_invoice(invoice_doc, lowercase_unit=True)

        self.assertEqual(len(payloads), 3)

        # First item checks
        self.assertEqual(payloads[0].line_item_id, "item-1")
        self.assertEqual(payloads[0].raw_item_description, "Amul Pasteurised Butter 500g")
        self.assertEqual(payloads[0].quantity, Decimal("2"))
        self.assertEqual(payloads[0].unit, "pack")
        self.assertEqual(payloads[0].platform, "BLINKIT")
        self.assertEqual(payloads[0].metadata["supplier_name"], "Blinkit Quick Commerce")
        self.assertEqual(payloads[0].metadata["invoice_number"], "BLK/2026/0042")

        # Second item checks
        self.assertEqual(payloads[1].line_item_id, "item-2")
        self.assertEqual(payloads[1].quantity, Decimal("6"))
        self.assertEqual(payloads[1].unit, "can")

        # Third item checks (delivery fee without quantity)
        self.assertEqual(payloads[2].line_item_id, "item-3")
        self.assertIsNone(payloads[2].quantity)
        self.assertTrue(payloads[2].metadata["is_quantity_missing"])
        self.assertEqual(payloads[2].metadata["quantity_indicator"], "MISSING")

        # Verify all payloads serialize to dict
        for p in payloads:
            d = p.to_dict()
            self.assertIn("line_item_id", d)
            self.assertIn("raw_item_description", d)
            self.assertIn("quantity", d)
            self.assertIn("metadata", d)


if __name__ == "__main__":
    unittest.main()
