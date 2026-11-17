"""
Cross-Track Adapter: Track B (Invoice Extraction) to Track C (Item Screening).

Provides a pure, decoupled, lossless transformation from Track B extracted invoice
line items and metadata into Track C screening input payloads.

Key Invariants:
1. Pure Decoupled Transformation: Zero imports of Track C policy rules, engines,
   or external database models.
2. Lossless Numerical Integrity: Preserves exact decimal.Decimal quantities
   (never converts through binary IEEE 754 float).
3. Null Quantity Preservation & Provenance: Nullable quantity remains None
   (with metadata indicators 'is_quantity_missing' and 'quantity_indicator'),
   or optionally filled with an explicit default quantity when requested.
4. Unit Taxonomy Normalization: Maps unit strings through canonical representation
   ('unit', 'kg', 'g', 'pack', 'box', 'bottle', 'ltr', etc.) while keeping
   unrecognized units intact without corruption.
5. Audit Provenance: Preserves original line_item_id, unmodified raw item description,
   normalized description, document ID, page, and bounding box evidence.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, List, Optional, Union


# Canonical Upper-Case Unit Taxonomy (matching review contract)
CANONICAL_UNIT_MAP_UPPER: Dict[str, str] = {
    "pcs": "PCS",
    "pc": "PCS",
    "pieces": "PCS",
    "piece": "PCS",
    "nos": "NOS",
    "no": "NOS",
    "no.": "NOS",
    "unit": "UNIT",
    "units": "UNIT",
    "ea": "UNIT",
    "each": "UNIT",
    "item": "UNIT",
    "items": "UNIT",
    "kg": "KG",
    "kgs": "KG",
    "kilogram": "KG",
    "kilograms": "KG",
    "g": "G",
    "gm": "G",
    "gms": "G",
    "gram": "G",
    "grams": "G",
    "mg": "MG",
    "mgs": "MG",
    "milligram": "MG",
    "milligrams": "MG",
    "ltr": "LTR",
    "l": "LTR",
    "liter": "LTR",
    "liters": "LTR",
    "litre": "LTR",
    "litres": "LTR",
    "ml": "ML",
    "mls": "ML",
    "milliliter": "ML",
    "milliliters": "ML",
    "box": "BOX",
    "boxes": "BOX",
    "bx": "BOX",
    "bxs": "BOX",
    "pack": "PACK",
    "packs": "PACK",
    "pkt": "PACK",
    "pkts": "PACK",
    "packet": "PACK",
    "packets": "PACK",
    "dozen": "DOZ",
    "doz": "DOZ",
    "dz": "DOZ",
    "can": "CAN",
    "cans": "CAN",
    "bottle": "BOTTLE",
    "bottles": "BOTTLE",
    "btl": "BOTTLE",
    "btls": "BOTTLE",
    "strip": "STRIP",
    "strips": "STRIP",
    "vial": "VIAL",
    "vials": "VIAL",
    "bag": "BAG",
    "bags": "BAG",
    "meter": "METER",
    "meters": "METER",
    "m": "METER",
}

# Canonical Lower-Case Unit Vocabulary
CANONICAL_UNIT_MAP_LOWER: Dict[str, str] = {
    # count / piece
    "pcs": "unit",
    "pc": "unit",
    "pieces": "unit",
    "piece": "unit",
    "nos": "unit",
    "no": "unit",
    "no.": "unit",
    "unit": "unit",
    "units": "unit",
    "ea": "unit",
    "each": "unit",
    "item": "unit",
    "items": "unit",
    # mass
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "g": "g",
    "gm": "g",
    "gms": "g",
    "gram": "g",
    "grams": "g",
    "mg": "mg",
    "mgs": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    # volume
    "ltr": "l",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "ml": "ml",
    "mls": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    # packaging
    "pack": "pack",
    "packs": "pack",
    "pkt": "pack",
    "pkts": "pack",
    "packet": "pack",
    "packets": "pack",
    "box": "box",
    "boxes": "box",
    "bx": "box",
    "bxs": "box",
    "carton": "box",
    "cartons": "box",
    "bottle": "bottle",
    "bottles": "bottle",
    "btl": "bottle",
    "btls": "bottle",
    "can": "can",
    "cans": "can",
    "strip": "strip",
    "strips": "strip",
    "vial": "vial",
    "vials": "vial",
    "bag": "bag",
    "bags": "bag",
    "dozen": "dozen",
    "doz": "dozen",
    "dz": "dozen",
    "meter": "meter",
    "meters": "meter",
    "m": "meter",
}

# Alias for backward compatibility
CANONICAL_UNIT_MAP = CANONICAL_UNIT_MAP_UPPER

# Known vendor name patterns to platform identifier mapping
VENDOR_TO_PLATFORM_MAP: Dict[str, str] = {
    "zomato": "ZOMATO",
    "blinkit": "BLINKIT",
    "zepto": "ZEPTO",
    "swiggy": "SWIGGY",
    "instamart": "SWIGGY_INSTAMART",
    "amazon": "AMAZON",
    "bigbasket": "BIGBASKET",
    "bbnow": "BIGBASKET",
    "dunzo": "DUNZO",
}


def normalize_screening_unit(raw_unit: Optional[str], lowercase: bool = False) -> Optional[str]:
    """
    Normalizes arbitrary unit strings to canonical Track C unit vocabulary.
    Returns None if raw_unit is None or empty.
    """
    if not raw_unit:
        return None
    cleaned = raw_unit.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowercase:
        return CANONICAL_UNIT_MAP_LOWER.get(lowered, lowered)
    return CANONICAL_UNIT_MAP_UPPER.get(lowered, cleaned.upper())


def infer_platform_from_vendor(vendor_name: Optional[str]) -> Optional[str]:
    """
    Infers delivery platform code from supplier or vendor name string.
    More specific / longer tokens are checked first (e.g. 'instamart' before 'swiggy').
    """
    if not vendor_name:
        return None
    lowered = vendor_name.lower()
    for token, platform in sorted(VENDOR_TO_PLATFORM_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if token in lowered:
            return platform
    return None


def parse_exact_decimal_quantity(raw_val: Any) -> Optional[Decimal]:
    """
    Converts quantity safely into Decimal without floating-point loss.
    Preserves None when missing or unparseable. Never silently coerces to 0 or 1.
    """
    if raw_val is None:
        return None
    if isinstance(raw_val, Decimal):
        return raw_val
    if isinstance(raw_val, (int, float)):
        return Decimal(str(raw_val))
    s = str(raw_val).strip()
    if not s or s.lower() in ("null", "none", "nan", "undefined", ""):
        return None
    # Remove grouping commas if present
    s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class ScreeningItemInput:
    """
    Standardized, decoupled input for Track C screening classification and policy evaluation.
    Preserves exact Decimal precision and nullability invariants.
    """
    line_item_id: str
    raw_item_description: str
    normalized_description: str
    quantity: Optional[Decimal]
    unit: Optional[str]
    platform: Optional[str]
    document_id: str = ""
    unit_price: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    currency: Optional[str] = None
    source_page: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        line_item_id: str,
        raw_item_description: Optional[str] = None,
        normalized_description: Optional[str] = None,
        quantity: Optional[Decimal] = None,
        unit: Optional[str] = None,
        platform: Optional[str] = None,
        document_id: str = "",
        unit_price: Optional[Decimal] = None,
        line_total: Optional[Decimal] = None,
        currency: Optional[str] = None,
        source_page: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        raw_description: Optional[str] = None,
    ):
        desc = raw_item_description if raw_item_description is not None else (raw_description or "")
        norm = normalized_description if normalized_description is not None else desc
        object.__setattr__(self, "line_item_id", line_item_id)
        object.__setattr__(self, "raw_item_description", desc)
        object.__setattr__(self, "normalized_description", norm)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "unit_price", unit_price)
        object.__setattr__(self, "line_total", line_total)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "source_page", source_page)
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @property
    def raw_description(self) -> str:
        """Alias for backward compatibility with existing tests."""
        return self.raw_item_description

    def to_dict(self) -> Dict[str, Any]:
        """Serializes input to a JSON-compatible dictionary preserving Decimal representation."""
        return {
            "line_item_id": self.line_item_id,
            "raw_item_description": self.raw_item_description,
            "raw_description": self.raw_item_description,
            "normalized_description": self.normalized_description,
            "quantity": self.quantity,
            "unit": self.unit,
            "platform": self.platform,
            "document_id": self.document_id,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "currency": self.currency,
            "source_page": self.source_page,
            "metadata": dict(self.metadata),
        }

    def to_classification_input(self) -> Any:
        """
        Instantiates Track C ClassificationInput dataclass lazily if available.
        Decoupled at import time.
        """
        from research_track.track_c.src.types import ClassificationInput
        return ClassificationInput(
            line_item_id=self.line_item_id,
            raw_item_description=self.raw_item_description,
            normalized_description=self.normalized_description,
            quantity=self.quantity,
            unit=self.unit,
            platform=self.platform,
            metadata=dict(self.metadata),
        )


# Canonical alias
ScreeningInputPayload = ScreeningItemInput


class TrackBToCAdapter:
    """
    Transforms extracted and reconciled Track B invoice documents into Track C screening inputs.
    """

    @staticmethod
    def normalize_unit(raw_unit: Optional[str], lowercase: bool = False) -> Optional[str]:
        """Normalizes unit of measure to canonical taxonomy representation."""
        return normalize_screening_unit(raw_unit, lowercase=lowercase)

    @staticmethod
    def parse_quantity(raw_qty: Any) -> Optional[Decimal]:
        """Parses quantity safely into Decimal without floating point loss."""
        return parse_exact_decimal_quantity(raw_qty)

    @classmethod
    def adapt_line_item(
        cls,
        item: Dict[str, Any],
        document_id: str = "",
        index: int = 0,
        platform_hint: Optional[str] = None,
        default_quantity: Optional[Decimal] = None,
        lowercase_unit: bool = False,
    ) -> ScreeningItemInput:
        """
        Adapts a single invoice line item into a ScreeningItemInput.
        """
        raw_desc = str(item.get("description") or item.get("raw_item_description") or item.get("raw_description") or "").strip()
        norm_desc = str(item.get("normalized_description") or raw_desc).strip()
        if not raw_desc and not norm_desc:
            raw_desc = f"UNNAMED_ITEM_{index + 1}"
            norm_desc = raw_desc

        line_id = str(item.get("line_item_id") or (f"line-{document_id}-{index + 1}" if document_id else f"item-{index + 1}")).strip()
        parsed_qty = cls.parse_quantity(item.get("quantity"))

        metadata = dict(item.get("metadata") or {})
        metadata["original_index"] = index

        if document_id:
            metadata["source_document_id"] = document_id
        if item.get("unit_price") is not None:
            metadata["unit_price"] = str(item["unit_price"])
        if item.get("line_total") is not None:
            metadata["line_total"] = str(item["line_total"])
        if item.get("currency"):
            metadata["currency"] = item["currency"]
        if item.get("source_page") or item.get("page_number"):
            metadata["source_page"] = item.get("source_page") or item.get("page_number")
        if item.get("evidence"):
            metadata["evidence"] = item["evidence"]
        if item.get("unit"):
            metadata["raw_unit"] = item["unit"]

        if parsed_qty is None:
            if default_quantity is not None:
                final_qty = Decimal(str(default_quantity))
                metadata["is_quantity_missing"] = False
                metadata["quantity_indicator"] = "DEFAULTED"
                metadata["quantity_defaulted"] = True
            else:
                final_qty = None
                metadata["is_quantity_missing"] = True
                metadata["quantity_indicator"] = "MISSING"
        else:
            final_qty = parsed_qty
            metadata["is_quantity_missing"] = False
            metadata["quantity_indicator"] = "PRESENT"

        unit = cls.normalize_unit(item.get("unit"), lowercase=lowercase_unit)
        unit_price = cls.parse_quantity(item.get("unit_price"))
        line_total = cls.parse_quantity(item.get("line_total"))
        currency = item.get("currency")
        source_page = item.get("source_page") or item.get("page_number")
        if source_page is not None:
            try:
                source_page = int(source_page)
            except (ValueError, TypeError):
                source_page = None

        return ScreeningItemInput(
            line_item_id=line_id,
            raw_item_description=raw_desc,
            normalized_description=norm_desc,
            quantity=final_qty,
            unit=unit,
            platform=platform_hint,
            document_id=document_id,
            unit_price=unit_price,
            line_total=line_total,
            currency=currency,
            source_page=source_page,
            metadata=metadata,
        )

    @classmethod
    def adapt_invoice(
        cls,
        invoice_doc: Any,
        platform_hint: Optional[str] = None,
        default_quantity: Optional[Decimal] = None,
        lowercase_unit: bool = False,
    ) -> List[ScreeningItemInput]:
        """
        Transforms an entire extracted invoice into a list of ScreeningItemInput objects.
        """
        # Handle ExtractionResult / candidate objects if passed
        if hasattr(invoice_doc, "best_candidate") and invoice_doc.best_candidate:
            doc = invoice_doc.best_candidate.invoice
        elif hasattr(invoice_doc, "invoice"):
            doc = invoice_doc.invoice
        elif isinstance(invoice_doc, dict):
            doc = invoice_doc
        elif isinstance(invoice_doc, list):
            doc = {"line_items": invoice_doc}
        else:
            raise ValueError(f"Unsupported invoice input type: {type(invoice_doc)}")

        doc_id = str(doc.get("document_id") or "UNKNOWN_DOC").strip()
        supplier = doc.get("supplier_name")
        effective_platform = platform_hint or infer_platform_from_vendor(supplier) or supplier

        items = doc.get("line_items") or []
        adapted: List[ScreeningItemInput] = []

        for idx, item in enumerate(items):
            adapted_item = cls.adapt_line_item(
                item=item,
                document_id=doc_id,
                index=idx,
                platform_hint=effective_platform,
                default_quantity=default_quantity,
                lowercase_unit=lowercase_unit,
            )
            # Add invoice-level context to metadata
            if doc.get("invoice_number"):
                adapted_item.metadata["invoice_number"] = doc["invoice_number"]
            if supplier:
                adapted_item.metadata["supplier_name"] = supplier
            if doc.get("invoice_date"):
                adapted_item.metadata["invoice_date"] = doc["invoice_date"]
            if doc.get("currency") and not adapted_item.currency:
                object.__setattr__(adapted_item, "currency", doc["currency"])
                adapted_item.metadata["currency"] = doc["currency"]

            adapted.append(adapted_item)

        return adapted


def convert_line_item_to_screening_input(
    item: Dict[str, Any],
    platform: Optional[str] = None,
    invoice_context: Optional[Dict[str, Any]] = None,
    default_quantity: Optional[Decimal] = None,
    index_fallback: int = 1,
    lowercase_unit: bool = False,
) -> ScreeningItemInput:
    """
    Convenience function to transform a single line item into ScreeningItemInput.
    """
    ctx = invoice_context or {}
    doc_id = ctx.get("document_id", "")
    effective_platform = platform or ctx.get("platform") or infer_platform_from_vendor(ctx.get("supplier_name"))
    payload = TrackBToCAdapter.adapt_line_item(
        item=item,
        document_id=doc_id,
        index=index_fallback - 1,
        platform_hint=effective_platform,
        default_quantity=default_quantity,
        lowercase_unit=lowercase_unit,
    )
    if ctx.get("invoice_number"):
        payload.metadata["invoice_number"] = ctx["invoice_number"]
    if ctx.get("supplier_name"):
        payload.metadata["supplier_name"] = ctx["supplier_name"]
    if ctx.get("invoice_date"):
        payload.metadata["invoice_date"] = ctx["invoice_date"]
    return payload


def convert_invoice_to_screening_payloads(
    invoice_or_result: Any,
    platform: Optional[str] = None,
    default_quantity: Optional[Decimal] = None,
    lowercase_unit: bool = False,
) -> List[ScreeningItemInput]:
    """
    Convenience function to transform an invoice into a list of ScreeningItemInput payloads.
    """
    return TrackBToCAdapter.adapt_invoice(
        invoice_doc=invoice_or_result,
        platform_hint=platform,
        default_quantity=default_quantity,
        lowercase_unit=lowercase_unit,
    )
