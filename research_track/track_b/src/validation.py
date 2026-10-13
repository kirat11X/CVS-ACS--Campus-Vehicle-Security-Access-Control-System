"""
Track B: Deterministic Validation & Arithmetic Verification Module.

Performs rigorous, decimal-safe arithmetic and structural verification across
extracted invoice line items and invoice-level totals.

Invariants:
- Validation is purely diagnostic: it never fabricates missing numbers or mutates extracted values.
- Uses decimal.Decimal with documented rounding tolerances (e.g. 0.02) to evaluate financial consistency.
- Emits structured ValidationFinding objects with stable reason codes, severity levels,
  and human-review indicators.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationSeverity(str, Enum):
    """Severity of a validation discrepancy."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ReasonCode(str, Enum):
    """Stable, standardized reason codes for audit trails."""
    VAL_SCHEMA_VIOLATION = "VAL_SCHEMA_VIOLATION"
    VAL_LINE_ARITHMETIC_MISMATCH = "VAL_LINE_ARITHMETIC_MISMATCH"
    VAL_LINE_DISCOUNT_INVALID = "VAL_LINE_DISCOUNT_INVALID"
    VAL_LINE_TAX_MISMATCH = "VAL_LINE_TAX_MISMATCH"
    VAL_NEGATIVE_QUANTITY = "VAL_NEGATIVE_QUANTITY"
    VAL_NEGATIVE_UNIT_PRICE = "VAL_NEGATIVE_UNIT_PRICE"
    VAL_SUBTOTAL_MISMATCH = "VAL_SUBTOTAL_MISMATCH"
    VAL_TAX_TOTAL_MISMATCH = "VAL_TAX_TOTAL_MISMATCH"
    VAL_GRAND_TOTAL_MISMATCH = "VAL_GRAND_TOTAL_MISMATCH"
    VAL_PAYMENT_BALANCE_MISMATCH = "VAL_PAYMENT_BALANCE_MISMATCH"
    VAL_MISSING_MANDATORY_FIELD = "VAL_MISSING_MANDATORY_FIELD"
    VAL_UNREADABLE_FIELD = "VAL_UNREADABLE_FIELD"
    VAL_CURRENCY_INCONSISTENCY = "VAL_CURRENCY_INCONSISTENCY"
    VAL_DUPLICATE_ITEM_DESCRIPTION = "VAL_DUPLICATE_ITEM_DESCRIPTION"
    VAL_SUSPICIOUS_ROUNDING = "VAL_SUSPICIOUS_ROUNDING"


@dataclass(frozen=True)
class ValidationFinding:
    """An immutable, auditable validation finding."""
    code: ReasonCode
    severity: ValidationSeverity
    field_or_line_id: Optional[str]
    expected_value: Optional[str]
    observed_value: Optional[str]
    difference: Optional[str]
    message: str
    requires_human_review: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "field_or_line_id": self.field_or_line_id,
            "expected_value": self.expected_value,
            "observed_value": self.observed_value,
            "difference": self.difference,
            "message": self.message,
            "requires_human_review": self.requires_human_review,
        }


class DeterministicValidator:
    """
    Performs deterministic arithmetic checks on extracted invoice structures.
    """

    def __init__(
        self,
        rounding_tolerance: Decimal = Decimal("0.02"),
        tax_tolerance: Decimal = Decimal("0.05"),
        require_supplier: bool = True,
        require_invoice_number: bool = True,
        require_invoice_date: bool = True,
    ):
        self.rounding_tolerance = rounding_tolerance
        self.tax_tolerance = tax_tolerance
        self.require_supplier = require_supplier
        self.require_invoice_number = require_invoice_number
        self.require_invoice_date = require_invoice_date

    def validate_invoice(self, invoice: Dict[str, Any]) -> List[ValidationFinding]:
        """
        Executes complete validation suite on normalized invoice dictionary.
        Returns a list of structured ValidationFinding records.
        """
        findings: List[ValidationFinding] = []

        # 1. Structural and Mandatory Metadata Checks
        self._check_mandatory_fields(invoice, findings)

        # 2. Line Item Level Checks
        line_items = invoice.get("line_items") or []
        self._validate_line_items(line_items, invoice.get("currency"), findings)

        # 3. Invoice Totals and Reconciliation Checks
        totals = invoice.get("totals") or {}
        self._validate_totals(line_items, totals, findings)

        return findings

    def _check_mandatory_fields(self, invoice: Dict[str, Any], findings: List[ValidationFinding]) -> None:
        """Verifies existence of essential header metadata."""
        if self.require_invoice_number and not invoice.get("invoice_number"):
            findings.append(ValidationFinding(
                code=ReasonCode.VAL_MISSING_MANDATORY_FIELD,
                severity=ValidationSeverity.WARNING,
                field_or_line_id="invoice_number",
                expected_value="Non-empty identifier string",
                observed_value=str(invoice.get("invoice_number")),
                difference=None,
                message="Invoice number is missing or unreadable.",
                requires_human_review=True,
            ))

        if self.require_supplier and not invoice.get("supplier_name"):
            findings.append(ValidationFinding(
                code=ReasonCode.VAL_MISSING_MANDATORY_FIELD,
                severity=ValidationSeverity.WARNING,
                field_or_line_id="supplier_name",
                expected_value="Vendor / Supplier name",
                observed_value=str(invoice.get("supplier_name")),
                difference=None,
                message="Supplier / vendor name is missing or unreadable.",
                requires_human_review=True,
            ))

        if self.require_invoice_date and not invoice.get("invoice_date"):
            findings.append(ValidationFinding(
                code=ReasonCode.VAL_MISSING_MANDATORY_FIELD,
                severity=ValidationSeverity.WARNING,
                field_or_line_id="invoice_date",
                expected_value="ISO 8601 date string",
                observed_value=str(invoice.get("invoice_date")),
                difference=None,
                message="Invoice date is missing or could not be parsed.",
                requires_human_review=True,
            ))

    def _validate_line_items(
        self,
        line_items: List[Dict[str, Any]],
        invoice_currency: Optional[str],
        findings: List[ValidationFinding]
    ) -> None:
        """Validates arithmetic consistency of individual line items."""
        seen_descriptions = set()

        for idx, item in enumerate(line_items):
            line_id = item.get("line_item_id") or f"line-{idx + 1}"
            desc = (item.get("description") or "").strip()

            # Duplicate description check (informational)
            if desc and desc in seen_descriptions:
                findings.append(ValidationFinding(
                    code=ReasonCode.VAL_DUPLICATE_ITEM_DESCRIPTION,
                    severity=ValidationSeverity.INFO,
                    field_or_line_id=line_id,
                    expected_value="Unique item description",
                    observed_value=desc,
                    difference=None,
                    message=f"Duplicate item description '{desc}' appears on multiple lines.",
                    requires_human_review=False,
                ))
            if desc:
                seen_descriptions.add(desc)

            # Currency match check
            item_curr = item.get("currency")
            if item_curr and invoice_currency and item_curr != invoice_currency:
                findings.append(ValidationFinding(
                    code=ReasonCode.VAL_CURRENCY_INCONSISTENCY,
                    severity=ValidationSeverity.ERROR,
                    field_or_line_id=line_id,
                    expected_value=invoice_currency,
                    observed_value=item_curr,
                    difference=None,
                    message=f"Line currency '{item_curr}' differs from invoice currency '{invoice_currency}'.",
                    requires_human_review=True,
                ))

            qty = self._to_decimal(item.get("quantity"))
            u_price = self._to_decimal(item.get("unit_price"))
            line_total = self._to_decimal(item.get("line_total"))
            discount = self._to_decimal(item.get("discount_amount")) or Decimal("0.00")
            tax_rate = self._to_decimal(item.get("tax_rate"))
            tax_amt = self._to_decimal(item.get("tax_amount"))

            # Check for negative quantity or negative unit price
            if qty is not None and qty < Decimal("0.00"):
                findings.append(ValidationFinding(
                    code=ReasonCode.VAL_NEGATIVE_QUANTITY,
                    severity=ValidationSeverity.WARNING,
                    field_or_line_id=line_id,
                    expected_value=">= 0.00",
                    observed_value=f"{qty:.2f}",
                    difference=None,
                    message=f"Line item '{line_id}' has negative quantity (may represent a return or credit).",
                    requires_human_review=True,
                ))

            if u_price is not None and u_price < Decimal("0.00"):
                findings.append(ValidationFinding(
                    code=ReasonCode.VAL_NEGATIVE_UNIT_PRICE,
                    severity=ValidationSeverity.ERROR,
                    field_or_line_id=line_id,
                    expected_value=">= 0.00",
                    observed_value=f"{u_price:.2f}",
                    difference=None,
                    message=f"Line item '{line_id}' has negative unit price.",
                    requires_human_review=True,
                ))

            # Arithmetic check: quantity * unit_price - discount == line_total
            if qty is not None and u_price is not None and line_total is not None:
                expected_total = (qty * u_price) - discount
                diff = abs(line_total - expected_total)
                if diff > self.rounding_tolerance:
                    findings.append(ValidationFinding(
                        code=ReasonCode.VAL_LINE_ARITHMETIC_MISMATCH,
                        severity=ValidationSeverity.ERROR,
                        field_or_line_id=line_id,
                        expected_value=f"{expected_total:.2f}",
                        observed_value=f"{line_total:.2f}",
                        difference=f"{diff:.2f}",
                        message=(
                            f"Line '{line_id}' arithmetic mismatch: "
                            f"{qty} x {u_price:.2f} - {discount:.2f} = {expected_total:.2f}, "
                            f"but reported line_total is {line_total:.2f} (diff: {diff:.2f})."
                        ),
                        requires_human_review=True,
                    ))

            # Tax check if tax_rate and tax_amount provided
            if tax_rate is not None and tax_amt is not None and line_total is not None:
                # Expected tax = (line_total or (qty * u_price)) * (tax_rate / 100)
                base = (qty * u_price) if (qty is not None and u_price is not None) else line_total
                expected_tax = base * (tax_rate / Decimal("100.00"))
                tax_diff = abs(tax_amt - expected_tax)
                if tax_diff > self.tax_tolerance:
                    findings.append(ValidationFinding(
                        code=ReasonCode.VAL_LINE_TAX_MISMATCH,
                        severity=ValidationSeverity.WARNING,
                        field_or_line_id=line_id,
                        expected_value=f"{expected_tax:.2f}",
                        observed_value=f"{tax_amt:.2f}",
                        difference=f"{tax_diff:.2f}",
                        message=(
                            f"Line '{line_id}' tax mismatch: "
                            f"{base:.2f} at {tax_rate}% = {expected_tax:.2f}, but reported tax is {tax_amt:.2f}."
                        ),
                        requires_human_review=False,
                    ))

    def _validate_totals(
        self,
        line_items: List[Dict[str, Any]],
        totals: Dict[str, Any],
        findings: List[ValidationFinding]
    ) -> None:
        """Validates invoice-level totals against aggregated line items."""
        subtotal = self._to_decimal(totals.get("subtotal"))
        tax_total = self._to_decimal(totals.get("tax_total"))
        discount_total = self._to_decimal(totals.get("discount_total")) or Decimal("0.00")
        shipping_total = self._to_decimal(totals.get("shipping_total")) or Decimal("0.00")
        grand_total = self._to_decimal(totals.get("grand_total"))
        amount_paid = self._to_decimal(totals.get("amount_paid"))
        amount_due = self._to_decimal(totals.get("amount_due"))

        # 1. Sum of line totals vs Subtotal
        if line_items:
            valid_line_totals = [self._to_decimal(it.get("line_total")) for it in line_items]
            if all(v is not None for v in valid_line_totals):
                sum_line_totals = sum(valid_line_totals, Decimal("0.00"))
                if subtotal is not None:
                    diff = abs(sum_line_totals - subtotal)
                    if diff > self.rounding_tolerance:
                        findings.append(ValidationFinding(
                            code=ReasonCode.VAL_SUBTOTAL_MISMATCH,
                            severity=ValidationSeverity.ERROR,
                            field_or_line_id="totals.subtotal",
                            expected_value=f"{sum_line_totals:.2f}",
                            observed_value=f"{subtotal:.2f}",
                            difference=f"{diff:.2f}",
                            message=(
                                f"Sum of {len(line_items)} line totals ({sum_line_totals:.2f}) "
                                f"does not match reported subtotal ({subtotal:.2f}, diff: {diff:.2f})."
                            ),
                            requires_human_review=True,
                        ))

            # 2. Sum of line taxes vs reported tax_total
            valid_line_taxes = [self._to_decimal(it.get("tax_amount")) for it in line_items if it.get("tax_amount") is not None]
            if valid_line_taxes and tax_total is not None:
                sum_line_taxes = sum(valid_line_taxes, Decimal("0.00"))
                diff_tax = abs(sum_line_taxes - tax_total)
                if diff_tax > self.tax_tolerance:
                    findings.append(ValidationFinding(
                        code=ReasonCode.VAL_TAX_TOTAL_MISMATCH,
                        severity=ValidationSeverity.WARNING,
                        field_or_line_id="totals.tax_total",
                        expected_value=f"{sum_line_taxes:.2f}",
                        observed_value=f"{tax_total:.2f}",
                        difference=f"{diff_tax:.2f}",
                        message=(
                            f"Sum of line-item taxes ({sum_line_taxes:.2f}) differs from "
                            f"reported tax total ({tax_total:.2f}, diff: {diff_tax:.2f})."
                        ),
                        requires_human_review=False,
                    ))

        # 3. Subtotal + tax + shipping - discounts vs Grand Total
        if grand_total is not None:
            # If subtotal is present, check grand total formula
            if subtotal is not None:
                tax_term = tax_total or Decimal("0.00")
                expected_grand = subtotal + tax_term + shipping_total - discount_total
                diff_grand = abs(grand_total - expected_grand)
                if diff_grand > self.rounding_tolerance:
                    findings.append(ValidationFinding(
                        code=ReasonCode.VAL_GRAND_TOTAL_MISMATCH,
                        severity=ValidationSeverity.CRITICAL,
                        field_or_line_id="totals.grand_total",
                        expected_value=f"{expected_grand:.2f}",
                        observed_value=f"{grand_total:.2f}",
                        difference=f"{diff_grand:.2f}",
                        message=(
                            f"Grand total reconciliation failed: subtotal ({subtotal:.2f}) + "
                            f"tax ({tax_term:.2f}) + shipping ({shipping_total:.2f}) - "
                            f"discount ({discount_total:.2f}) = {expected_grand:.2f}, "
                            f"but reported grand total is {grand_total:.2f} (diff: {diff_grand:.2f})."
                        ),
                        requires_human_review=True,
                    ))
        else:
            findings.append(ValidationFinding(
                code=ReasonCode.VAL_MISSING_MANDATORY_FIELD,
                severity=ValidationSeverity.CRITICAL,
                field_or_line_id="totals.grand_total",
                expected_value="Grand total amount",
                observed_value=None,
                difference=None,
                message="Invoice is missing grand total.",
                requires_human_review=True,
            ))

        # 4. Payment reconciliation: amount_paid + amount_due == grand_total
        if grand_total is not None and amount_paid is not None and amount_due is not None:
            expected_due = grand_total - amount_paid
            diff_due = abs(amount_due - expected_due)
            if diff_due > self.rounding_tolerance:
                findings.append(ValidationFinding(
                    code=ReasonCode.VAL_PAYMENT_BALANCE_MISMATCH,
                    severity=ValidationSeverity.WARNING,
                    field_or_line_id="totals.amount_due",
                    expected_value=f"{expected_due:.2f}",
                    observed_value=f"{amount_due:.2f}",
                    difference=f"{diff_due:.2f}",
                    message=(
                        f"Payment balance mismatch: grand total ({grand_total:.2f}) - "
                        f"amount paid ({amount_paid:.2f}) = {expected_due:.2f}, "
                        f"but reported amount due is {amount_due:.2f}."
                    ),
                    requires_human_review=True,
                ))

    @staticmethod
    def _to_decimal(val: Any) -> Optional[Decimal]:
        """Safely converts input to Decimal without floating-point artifacts."""
        if val is None:
            return None
        if isinstance(val, Decimal):
            return val
        try:
            return Decimal(str(val).strip())
        except Exception:
            return None
