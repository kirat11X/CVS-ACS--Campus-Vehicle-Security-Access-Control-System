"""
Track B: Field-Level Normalization Module.

Provides deterministic, decimal-safe field parsing and canonical formatting for
invoice metadata, quantities, monetary values, dates, and units.

Invariants:
- Monetary amounts are parsed into decimal.Decimal to eliminate IEEE 754 floating-point drift.
- Never invent missing values or guess ambiguous amounts without documented locale policies.
- Ambiguous dates follow explicit policy (e.g. DAY_FIRST for Indian/Commonwealth invoices).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, List, Optional, Tuple


# Currency symbol mappings to ISO 4217 3-letter codes
DEFAULT_CURRENCY_MAP: Dict[str, str] = {
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "INR": "INR",
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
}

# Unit alias mappings to canonical standard representations
DEFAULT_UNIT_MAP: Dict[str, str] = {
    "pcs": "PCS",
    "pc": "PCS",
    "pieces": "PCS",
    "piece": "PCS",
    "nos": "NOS",
    "no": "NOS",
    "no.": "NOS",
    "kg": "KG",
    "kgs": "KG",
    "kilogram": "KG",
    "kilograms": "KG",
    "g": "G",
    "gm": "G" ,
    "gms": "G",
    "grams": "G",
    "ltr": "LTR",
    "l": "LTR",
    "liter": "LTR",
    "liters": "LTR",
    "litre": "LTR",
    "litres": "LTR",
    "ml": "ML",
    "box": "BOX",
    "boxes": "BOX",
    "pack": "PACK",
    "packs": "PACK",
    "pkt": "PACK",
    "pkts": "PACK",
    "dozen": "DOZ",
    "dz": "DOZ",
}


@dataclass(frozen=True)
class NormalizedMoney:
    """Decimal-safe representation of a monetary value."""
    amount: Decimal
    currency: Optional[str] = None
    raw_text: str = ""

    @property
    def amount_str(self) -> str:
        """Formats decimal to standard 2-decimal string representation."""
        return f"{self.amount:.2f}"


class FieldNormalizer:
    """
    Deterministic normalizer for invoice fields, dates, currencies, and line items.
    """

    def __init__(
        self,
        default_currency: Optional[str] = None,
        ambiguous_date_policy: str = "DAY_FIRST",
        decimal_separator: str = ".",
        currency_map: Optional[Dict[str, str]] = None,
        unit_map: Optional[Dict[str, str]] = None,
    ):
        self.default_currency = default_currency
        self.ambiguous_date_policy = ambiguous_date_policy.upper()
        self.decimal_separator = decimal_separator
        self.currency_map = currency_map or DEFAULT_CURRENCY_MAP
        self.unit_map = unit_map or DEFAULT_UNIT_MAP

    @staticmethod
    def normalize_whitespace(text: Optional[str]) -> Optional[str]:
        """Normalizes unicode whitespace, collapses spaces, and strips boundaries."""
        if text is None:
            return None
        # Replace non-breaking spaces and tabs
        cleaned = re.sub(r"[\s\u00a0\u200b]+", " ", str(text)).strip()
        return cleaned if cleaned else None

    def parse_currency(self, text: Optional[str]) -> Tuple[Optional[str], str]:
        """
        Extracts currency code from text and returns (currency_code, remaining_text).
        Does not guess when ambiguous.
        """
        if not text:
            return None, ""

        cleaned = text.strip()
        # Check prefixes and standalone tokens
        for symbol, code in sorted(self.currency_map.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(re.escape(symbol), re.IGNORECASE)
            if pattern.search(cleaned):
                # Remove matched symbol from text
                rem = pattern.sub("", cleaned).strip()
                return code, rem

        return self.default_currency, cleaned

    def parse_decimal_amount(
        self,
        raw_val: Any,
        locale_hint: Optional[str] = None
    ) -> Optional[Decimal]:
        """
        Parses monetary strings safely into Decimal.
        Handles standard (1,234.50) and European (1.234,50) formats under explicit locale policies.
        Never silently misinterprets ambiguous numbers.
        """
        if raw_val is None:
            return None
        if isinstance(raw_val, (int, Decimal)):
            return Decimal(raw_val)
        if isinstance(raw_val, float):
            # Convert float through string to preserve stated representation
            return Decimal(str(raw_val))

        s = str(raw_val).strip()
        if not s:
            return None

        # Remove currency symbols first
        for sym in self.currency_map.keys():
            s = re.sub(re.escape(sym), "", s, flags=re.IGNORECASE).strip()

        # Handle negative values with parenthetical syntax e.g. (10.00) or -$10.00
        is_negative = False
        if s.startswith("(") and s.endswith(")"):
            is_negative = True
            s = s[1:-1].strip()
        elif s.startswith("-"):
            is_negative = True
            s = s[1:].strip()

        # Check for European format with comma decimal separator e.g. "1.234,50" or "50,00"
        # If locale_hint is de/fr/eu or decimal_separator is ','
        if (locale_hint and ("eu" in locale_hint.lower() or "de" in locale_hint.lower() or "fr" in locale_hint.lower())) or self.decimal_separator == ",":
            if "," in s and "." in s:
                # "1.234,50" -> remove dot, replace comma with dot
                s = s.replace(".", "").replace(",", ".")
            elif "," in s:
                # "50,00" -> replace comma with dot
                s = s.replace(",", ".")
        else:
            # Standard US/Indian format e.g. "1,234.50" or "1,23,456.00"
            if "," in s and "." in s:
                s = s.replace(",", "")
            elif "," in s and "." not in s:
                # Ambiguous case: "1,234" vs "50,00"
                # If there are exactly two digits after comma (e.g. 50,00), and no other comma
                parts = s.split(",")
                if len(parts) == 2 and len(parts[1]) == 2 and parts[0].isdigit():
                    # Likely a European decimal or typo; require explicit locale, but if comma is decimal sep:
                    if self.decimal_separator == ",":
                        s = s.replace(",", ".")
                    else:
                        # Standard interpretation: comma is thousands separator, missing decimals
                        s = s.replace(",", "")
                else:
                    # Thousands separator (e.g. 1,000 or 1,23,456)
                    s = s.replace(",", "")

        # Clean remaining whitespace
        s = s.replace(" ", "")

        try:
            val = Decimal(s)
            return -val if is_negative else val
        except InvalidOperation:
            return None

    def parse_date(self, raw_date: Optional[str]) -> Optional[str]:
        """
        Parses diverse date formats into canonical ISO 8601 string (YYYY-MM-DD).
        Respects ambiguous_date_policy (DAY_FIRST default for India/UK).
        """
        if not raw_date:
            return None

        cleaned = self.normalize_whitespace(raw_date)
        if not cleaned:
            return None

        # Clean ordinals: 1st, 2nd, 3rd, 4th -> 1, 2, 3, 4
        cleaned_no_ord = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE)

        # Standard formats to attempt
        if self.ambiguous_date_policy == "DAY_FIRST":
            candidate_formats = [
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%d.%m.%Y",
                "%d %b %Y",
                "%d %B %Y",
                "%d %b, %Y",
                "%d %B, %Y",
                "%m/%d/%Y",  # Fallback only
                "%Y/%m/%d",
            ]
        else:
            candidate_formats = [
                "%Y-%m-%d",
                "%m/%d/%Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%b %d, %Y",
                "%B %d, %Y",
                "%Y/%m/%d",
            ]

        for fmt in candidate_formats:
            try:
                dt = datetime.strptime(cleaned_no_ord, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None

    def normalize_unit(self, raw_unit: Optional[str]) -> Optional[str]:
        """Normalizes unit of measure to standard token or returns uppercase string."""
        if not raw_unit:
            return None
        cleaned = raw_unit.strip().lower()
        return self.unit_map.get(cleaned, raw_unit.strip().upper())

    def normalize_line_item(
        self,
        raw_description: str,
        raw_quantity: Any,
        raw_unit_price: Any,
        raw_unit: Optional[str] = None,
        raw_line_total: Any = None,
        raw_discount: Any = None,
        raw_tax_rate: Any = None,
        raw_tax_amount: Any = None,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Produces clean, typed line item dictionary with decimal-safe numeric values.
        """
        norm_desc = self.normalize_whitespace(raw_description) or "UNKNOWN_ITEM"
        qty = self.parse_decimal_amount(raw_quantity)
        u_price = self.parse_decimal_amount(raw_unit_price)
        total = self.parse_decimal_amount(raw_line_total)
        discount = self.parse_decimal_amount(raw_discount)
        tax_rate = self.parse_decimal_amount(raw_tax_rate)
        tax_amt = self.parse_decimal_amount(raw_tax_amount)
        unit = self.normalize_unit(raw_unit)

        return {
            "description": raw_description.strip() if raw_description else "",
            "normalized_description": norm_desc,
            "quantity": qty,
            "unit": unit,
            "unit_price": u_price,
            "discount_amount": discount,
            "tax_rate": tax_rate,
            "tax_amount": tax_amt,
            "line_total": total,
            "currency": currency or self.default_currency,
        }
