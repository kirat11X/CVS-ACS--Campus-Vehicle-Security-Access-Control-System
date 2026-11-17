"""
Tests for the Track B -> Track C Pure Review Adapter (Decision 5 / X-S1-001).
Verifies lossless Decimal preservation, null preservation, unit taxonomy mapping,
and line ID stability without importing Track C policy or database models.
"""

from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest

_ADAPTER_PATH = Path(__file__).resolve().parents[2] / "track_b" / "src" / "adapter_c.py"
_spec = importlib.util.spec_from_file_location("adapter_c_isolated", _ADAPTER_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

ScreeningItemInput = _module.ScreeningItemInput
TrackBToCAdapter = _module.TrackBToCAdapter


class TestTrackBToCAdapter(unittest.TestCase):

    def test_lossless_decimal_quantity_preservation(self):
        item = {
            "line_item_id": "item-101",
            "description": "Lab Grade Ethanol 99%",
            "quantity": "2.5",
            "unit": "litres",
            "unit_price": "450.50",
            "line_total": "1126.25",
        }
        res = TrackBToCAdapter.adapt_line_item(item, document_id="INV-001", index=0)
        self.assertEqual(res.line_item_id, "item-101")
        self.assertEqual(res.quantity, Decimal("2.5"))
        self.assertEqual(str(res.quantity), "2.5")
        self.assertEqual(res.unit, "LTR")
        self.assertEqual(res.line_total, Decimal("1126.25"))

    def test_null_quantity_preservation(self):
        # Must NOT convert missing quantity to 0 or 1
        item = {
            "description": "Delivery Express Service Charge",
            "quantity": None,
            "unit": None,
            "line_total": "150.00",
        }
        res = TrackBToCAdapter.adapt_line_item(item, document_id="INV-002", index=1)
        self.assertIsNone(res.quantity)
        self.assertEqual(res.line_item_id, "line-INV-002-2")
        self.assertIsNone(res.unit)

    def test_unit_taxonomy_canonicalization(self):
        test_cases = [
            ("kg", "KG"),
            ("kilograms", "KG"),
            ("pcs", "PCS"),
            ("pieces", "PCS"),
            ("litres", "LTR"),
            ("ml", "ML"),
            ("bottles", "BOTTLE"),
            ("unknown_metric_unit", "UNKNOWN_METRIC_UNIT"),
            ("", None),
            (None, None),
        ]
        for raw, expected in test_cases:
            self.assertEqual(TrackBToCAdapter.normalize_unit(raw), expected)

    def test_adapt_full_invoice(self):
        invoice = {
            "document_id": "AMZN-2026-9921",
            "supplier_name": "AMAZON_RETAIL",
            "line_items": [
                {
                    "line_item_id": "line-1",
                    "description": "HP Laser Printer Paper A4 500 Sheets",
                    "quantity": "5",
                    "unit": "packs",
                    "unit_price": "320.00",
                    "line_total": "1600.00",
                },
                {
                    "description": "Hydrochloric Acid 35% Technical Grade",
                    "quantity": "3.75",
                    "unit": "litres",
                    "unit_price": "200.00",
                    "line_total": "750.00",
                },
            ],
        }
        adapted = TrackBToCAdapter.adapt_invoice(invoice, platform_hint="AMAZON")
        self.assertEqual(len(adapted), 2)

        first = adapted[0]
        self.assertEqual(first.line_item_id, "line-1")
        self.assertEqual(first.quantity, Decimal("5"))
        self.assertEqual(first.unit, "PACK")
        self.assertEqual(first.platform, "AMAZON")

        second = adapted[1]
        self.assertEqual(second.line_item_id, "line-AMZN-2026-9921-2")
        self.assertEqual(second.quantity, Decimal("3.75"))
        self.assertEqual(second.unit, "LTR")
        self.assertEqual(second.platform, "AMAZON")


if __name__ == "__main__":
    unittest.main()
