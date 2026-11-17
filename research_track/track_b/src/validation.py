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
        """Validates invoice-level totals against aggregated line items and platform fee breakdowns."""
        subtotal = self._to_decimal(totals.get("subtotal"))
        tax_total = self._to_decimal(totals.get("tax_total"))
        discount_total = self._to_decimal(totals.get("discount_total")) or Decimal("0.00")
        shipping_total = self._to_decimal(totals.get("shipping_total"))
        delivery_fee = self._to_decimal(totals.get("delivery_fee"))
        # delivery_term: prefer explicit delivery_fee if provided, else shipping_total
        delivery_term = (delivery_fee if delivery_fee is not None else shipping_total) or Decimal("0.00")

        packaging_fee = (
            self._to_decimal(totals.get("packaging_fee"))
            or self._to_decimal(totals.get("packaging_charge"))
            or Decimal("0.00")
        )
        platform_fee = self._to_decimal(totals.get("platform_fee")) or Decimal("0.00")
        round_off = self._to_decimal(totals.get("round_off")) or Decimal("0.00")

        # Indian GST breakdown components (CGST, SGST, IGST)
        cgst = self._to_decimal(totals.get("cgst"))
        sgst = self._to_decimal(totals.get("sgst"))
        igst = self._to_decimal(totals.get("igst"))
        has_gst_components = (cgst is not None or sgst is not None or igst is not None)
        gst_components_sum = (cgst or Decimal("0.00")) + (sgst or Decimal("0.00")) + (igst or Decimal("0.00"))

        if has_gst_components and tax_total is not None:
            diff_gst = abs(tax_total - gst_components_sum)
            if diff_gst > self.tax_tolerance:
                findings.append(ValidationFinding(
                    code=ReasonCode.VAL_TAX_TOTAL_MISMATCH,
                    severity=ValidationSeverity.WARNING,
                    field_or_line_id="totals.tax_total",
                    expected_value=f"{gst_components_sum:.2f}",
                    observed_value=f"{tax_total:.2f}",
                    difference=f"{diff_gst:.2f}",
                    message=(
                        f"Reported tax_total ({tax_total:.2f}) differs from sum of "
                        f"CGST+SGST+IGST components ({gst_components_sum:.2f}, diff: {diff_gst:.2f})."
                    ),
                    requires_human_review=False,
                ))

        effective_tax_total = tax_total if tax_total is not None else (gst_components_sum if has_gst_components else None)

        # 1. Sum of line totals vs Subtotal
        valid_line_discounts = [self._to_decimal(it.get("discount_amount")) for it in line_items if it.get("discount_amount") is not None]
        sum_line_discounts = sum(valid_line_discounts, Decimal("0.00"))

        if line_items:
            valid_line_totals = [self._to_decimal(it.get("line_total")) for it in line_items]
            if all(v is not None for v in valid_line_totals):
                sum_line_totals = sum(valid_line_totals, Decimal("0.00"))
                if subtotal is not None:
                    diff_direct = abs(sum_line_totals - subtotal)
                    diff_with_item_discount = abs((sum_line_totals + sum_line_discounts) - subtotal)
                    diff_with_subtracted_item_discount = abs((sum_line_totals - sum_line_discounts) - subtotal)
                    diff_with_order_discount = abs((sum_line_totals - discount_total) - subtotal)

                    # Subtotal can be reported net of line totals or gross before item discounts
                    min_subtotal_diff = min(
                        diff_direct,
                        diff_with_item_discount,
                        diff_with_subtracted_item_discount,
                        diff_with_order_discount,
                    )
                    if min_subtotal_diff > self.rounding_tolerance:
                        findings.append(ValidationFinding(
                            code=ReasonCode.VAL_SUBTOTAL_MISMATCH,
                            severity=ValidationSeverity.ERROR,
                            field_or_line_id="totals.subtotal",
                            expected_value=f"{sum_line_totals:.2f}",
                            observed_value=f"{subtotal:.2f}",
                            difference=f"{diff_direct:.2f}",
                            message=(
                                f"Sum of {len(line_items)} line totals ({sum_line_totals:.2f}) "
                                f"does not match reported subtotal ({subtotal:.2f}, diff: {diff_direct:.2f})."
                            ),
                            requires_human_review=True,
                        ))

            # 2. Sum of line taxes vs reported tax_total
            valid_line_taxes = [self._to_decimal(it.get("tax_amount")) for it in line_items if it.get("tax_amount") is not None]
            if valid_line_taxes and effective_tax_total is not None:
                sum_line_taxes = sum(valid_line_taxes, Decimal("0.00"))
                diff_tax = abs(sum_line_taxes - effective_tax_total)
                if diff_tax > self.tax_tolerance:
                    findings.append(ValidationFinding(
                        code=ReasonCode.VAL_TAX_TOTAL_MISMATCH,
                        severity=ValidationSeverity.WARNING,
                        field_or_line_id="totals.tax_total",
                        expected_value=f"{sum_line_taxes:.2f}",
                        observed_value=f"{effective_tax_total:.2f}",
                        difference=f"{diff_tax:.2f}",
                        message=(
                            f"Sum of line-item taxes ({sum_line_taxes:.2f}) differs from "
                            f"reported tax total ({effective_tax_total:.2f}, diff: {diff_tax:.2f})."
                        ),
                        requires_human_review=False,
                    ))

        # 3. Subtotal + tax + platform fees (delivery, packaging, platform fee) - discounts + round_off vs Grand Total
        grand_total = self._to_decimal(totals.get("grand_total"))
        amount_paid = self._to_decimal(totals.get("amount_paid"))
        amount_due = self._to_decimal(totals.get("amount_due"))

        if grand_total is not None:
            if subtotal is not None:
                tax_term = effective_tax_total or Decimal("0.00")
                platform_charges = delivery_term + packaging_fee + platform_fee

                # Reconcile grand total under standard combinations:
                # 1. Standard: subtotal + tax + platform_charges - discount_total + round_off
                expected_std = subtotal + tax_term + platform_charges - discount_total + round_off
                diff_std = abs(grand_total - expected_std)

                # 2. Subtotal was already discounted, order discount not applied twice
                expected_no_discount = subtotal + tax_term + platform_charges + round_off
                diff_no_discount = abs(grand_total - expected_no_discount)

                # 3. Item discounts deducted instead of order discount
                expected_item_discount = subtotal + tax_term + platform_charges - sum_line_discounts + round_off
                diff_item_discount = abs(grand_total - expected_item_discount)

                best_diff = min(diff_std, diff_no_discount, diff_item_discount)
                if best_diff > self.rounding_tolerance:
                    findings.append(ValidationFinding(
                        code=ReasonCode.VAL_GRAND_TOTAL_MISMATCH,
                        severity=ValidationSeverity.CRITICAL,
                        field_or_line_id="totals.grand_total",
                        expected_value=f"{expected_std:.2f}",
                        observed_value=f"{grand_total:.2f}",
                        difference=f"{diff_std:.2f}",
                        message=(
                            f"Grand total reconciliation failed: subtotal ({subtotal:.2f}) + "
                            f"tax ({tax_term:.2f}) + platform charges ({platform_charges:.2f}) - "
                            f"discount ({discount_total:.2f}) + round_off ({round_off:.2f}) = {expected_std:.2f}, "
                            f"but reported grand total is {grand_total:.2f} (diff: {diff_std:.2f})."
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
