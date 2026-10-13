"""
Track B: Deterministic Baseline Invoice Extractor.

Parses documented, structured text invoices (tabular and key-value formatted synthetic text)
using deterministic regex and column heuristics without any neural or OCR inference.

Documented Format Scope & Limitations:
- Supports key-value header/footer metadata (e.g. 'Invoice Number:', 'Date:', 'Supplier:', 'Total:').
- Supports pipe-separated, tab-separated, and column-aligned line-item tables.
- Handles wrapped line-item descriptions when subsequent lines lack quantities.
- Explicitly DOES NOT handle arbitrary scanned visual layouts, complex multi-column wraps,
  or raster images. Unknown or unreadable fields remain None.
"""

from datetime import datetime, timezone
from decimal import Decimal
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .extraction_interface import (
    DocumentReference,
    ExtractionCandidate,
    ExtractionResult,
    InvoiceExtractor,
)
from .normalization import FieldNormalizer
from .validation import DeterministicValidator
from .reconciliation import InvoiceReconciler


class DeterministicBaselineExtractor(InvoiceExtractor):
    """
    Deterministic rule-based extractor for structured synthetic invoice texts.
    """

    def __init__(
        self,
        normalizer: Optional[FieldNormalizer] = None,
        validator: Optional[DeterministicValidator] = None,
        reconciler: Optional[InvoiceReconciler] = None,
    ):
        super().__init__(name="deterministic_baseline_v1", version="1.0.0")
        self.normalizer = normalizer or FieldNormalizer()
        self.validator = validator or DeterministicValidator()
        self.reconciler = reconciler or InvoiceReconciler(validator=self.validator)

    def extract(self, doc_ref: DocumentReference, raw_content: Any) -> ExtractionResult:
        """
        Parses structured synthetic invoice text into an auditable ExtractionResult.
        """
        start_time = time.perf_counter()
        timestamp = datetime.now(timezone.utc).isoformat()

        text = str(raw_content) if raw_content is not None else ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # 1. Parse Invoice-level Header & Metadata
        doc_id = doc_ref.document_id
        inv_number = self._extract_label_value(lines, [
            r"invoice\s*(?:#|no\.?|num(?:ber)?)\s*[:=-]\s*([^\n\r,;|]+)",
            r"bill\s*(?:#|no\.?)\s*[:=-]\s*([^\n\r,;|]+)",
        ])
        supplier = self._extract_label_value(lines, [
            r"(?:supplier|vendor|seller|from|store)\s*[:=-]\s*([^\n\r,;|]+)",
            r"(?:merchant)\s*[:=-]\s*([^\n\r,;|]+)",
        ])
        raw_date = self._extract_label_value(lines, [
            r"(?:invoice\s*)?date\s*[:=-]\s*([^\n\r,;|]+)",
            r"dated\s*[:=-]\s*([^\n\r,;|]+)",
        ])
        tax_id = self._extract_label_value(lines, [
            r"(?:gstin|vat|tax\s*id|ein)\s*[:=-]\s*([^\n\r,;|]+)",
        ])
        po_number = self._extract_label_value(lines, [
            r"(?:po|purchase\s*order)\s*(?:#|no\.?)?\s*[:=-]\s*([^\n\r,;|]+)",
        ])
        raw_currency = self._extract_label_value(lines, [
            r"currency\s*[:=-]\s*([A-Za-z$₹€£]+)",
        ])

        # Normalize Header Metadata
        norm_date = self.normalizer.parse_date(raw_date)
        currency_code, _ = self.normalizer.parse_currency(raw_currency or text)

        # 2. Extract Line Items
        raw_items, table_indices = self._extract_tabular_line_items(lines)
        line_items: List[Dict[str, Any]] = []

        for idx, item in enumerate(raw_items):
            line_id = f"item-{idx + 1}"
            norm_item = self.normalizer.normalize_line_item(
                raw_description=item.get("description", ""),
                raw_quantity=item.get("quantity"),
                raw_unit_price=item.get("unit_price"),
                raw_unit=item.get("unit"),
                raw_line_total=item.get("line_total"),
                raw_discount=item.get("discount"),
                raw_tax_rate=item.get("tax_rate"),
                raw_tax_amount=item.get("tax_amount"),
                currency=currency_code,
            )

            # Convert Decimals to DecimalString format for JSON schema compliance
            line_items.append({
                "line_item_id": line_id,
                "description": norm_item["description"],
                "normalized_description": norm_item["normalized_description"],
                "quantity": f"{norm_item['quantity']:.2f}" if norm_item["quantity"] is not None else None,
                "unit": norm_item["unit"],
                "unit_price": f"{norm_item['unit_price']:.2f}" if norm_item["unit_price"] is not None else None,
                "discount_amount": f"{norm_item['discount_amount']:.2f}" if norm_item["discount_amount"] is not None else None,
                "tax_rate": f"{norm_item['tax_rate']:.2f}" if norm_item["tax_rate"] is not None else None,
                "tax_amount": f"{norm_item['tax_amount']:.2f}" if norm_item["tax_amount"] is not None else None,
                "line_total": f"{norm_item['line_total']:.2f}" if norm_item["line_total"] is not None else None,
                "currency": currency_code,
                "source_page": 1,
                "evidence": None,
                "field_confidence": {
                    "description": 1.0,
                    "quantity": 1.0 if norm_item["quantity"] is not None else 0.0,
                    "unit_price": 1.0 if norm_item["unit_price"] is not None else 0.0,
                    "line_total": 1.0 if norm_item["line_total"] is not None else 0.0,
                },
                "missing_fields": [k for k in ["quantity", "unit_price", "line_total"] if norm_item.get(k) is None],
                "validation_warnings": [],
            })

        # 3. Extract Invoice Totals
        subtotal_raw = self._extract_label_value(lines, [
            r"sub\s*-?\s*total\s*[:=-]\s*([^\n\r;|]+)",
            r"net\s*amount\s*[:=-]\s*([^\n\r;|]+)",
        ])
        tax_total_raw = self._extract_label_value(lines, [
            r"(?:total\s*)?tax(?:es)?\s*[:=-]\s*([^\n\r;|]+)",
            r"(?:total\s*)?gst\s*[:=-]\s*([^\n\r;|]+)",
            r"(?:total\s*)?vat\s*[:=-]\s*([^\n\r;|]+)",
        ])
        discount_total_raw = self._extract_label_value(lines, [
            r"(?:total\s*)?discount\s*[:=-]\s*([^\n\r;|]+)",
        ])
        shipping_raw = self._extract_label_value(lines, [
            r"(?:shipping|delivery|freight)\s*(?:fee|charge)?\s*[:=-]\s*([^\n\r;|]+)",
        ])
        grand_total_raw = self._extract_label_value(lines, [
            r"(?:grand\s*total|total\s*payable|total\s*amount|balance\s*due|final\s*total)\s*[:=-]\s*([^\n\r;|]+)",
            r"(?<!sub)total\s*[:=-]\s*([^\n\r;|]+)",
        ])
        paid_raw = self._extract_label_value(lines, [
            r"(?:amount\s*)?paid\s*[:=-]\s*([^\n\r;|]+)",
        ])
        due_raw = self._extract_label_value(lines, [
            r"(?:amount\s*)?due\s*[:=-]\s*([^\n\r;|]+)",
        ])

        subtotal_dec = self.normalizer.parse_decimal_amount(subtotal_raw)
        tax_dec = self.normalizer.parse_decimal_amount(tax_total_raw)
        discount_dec = self.normalizer.parse_decimal_amount(discount_total_raw)
        shipping_dec = self.normalizer.parse_decimal_amount(shipping_raw)
        grand_total_dec = self.normalizer.parse_decimal_amount(grand_total_raw)
        paid_dec = self.normalizer.parse_decimal_amount(paid_raw)
        due_dec = self.normalizer.parse_decimal_amount(due_raw)

        totals = {
            "subtotal": f"{subtotal_dec:.2f}" if subtotal_dec is not None else None,
            "discount_total": f"{discount_dec:.2f}" if discount_dec is not None else None,
            "tax_total": f"{tax_dec:.2f}" if tax_dec is not None else None,
            "shipping_total": f"{shipping_dec:.2f}" if shipping_dec is not None else None,
            "grand_total": f"{grand_total_dec:.2f}" if grand_total_dec is not None else None,
            "amount_paid": f"{paid_dec:.2f}" if paid_dec is not None else None,
            "amount_due": f"{due_dec:.2f}" if due_dec is not None else None,
        }

        # 4. Construct Invoice Document Payload
        invoice_doc = {
            "schema_version": "1.0.0",
            "document_id": doc_id,
            "invoice_number": inv_number,
            "invoice_date": norm_date,
            "supplier_name": supplier,
            "supplier_tax_id": tax_id,
            "purchase_order_number": po_number,
            "currency": currency_code,
            "page_count": doc_ref.page_count or 1,
            "line_items": line_items,
            "totals": totals,
            "extraction_metadata": {
                "extractor_name": self.name,
                "extractor_version": self.version,
                "extraction_timestamp": timestamp,
                "provenance": {
                    "parser": "DeterministicBaselineExtractor",
                    "source_lines": len(lines),
                },
                "review_status": "AUTOMATED_RAW",
                "validation_findings_count": 0,
            },
        }

        # 5. Schema Pre-Validation
        schema_valid, schema_errs = self.validate_candidate(invoice_doc)

        # 6. Reconcile and Determine Status
        reconciliation_report = self.reconciler.reconcile(invoice_doc, schema_valid=schema_valid)
        invoice_doc["extraction_metadata"]["validation_findings_count"] = len(reconciliation_report.findings)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        candidate = ExtractionCandidate(
            candidate_id="cand-1",
            invoice=invoice_doc,
            ranking_score=1.0 if schema_valid else 0.0,
            rationale="Deterministic baseline regex and tabular parser output",
        )

        return ExtractionResult(
            schema_version="1.0.0",
            document_id=doc_id,
            extractor_name=self.name,
            extractor_version=self.version,
            execution_timestamp=timestamp,
            latency_ms=latency_ms,
            candidates=[candidate],
            selected_candidate_id="cand-1",
            reconciliation_status=reconciliation_report.status.value,
            requires_human_review=reconciliation_report.requires_human_review,
            validation_findings=[f.to_dict() for f in reconciliation_report.findings],
            schema_validation_errors=schema_errs,
            raw_output=text,
        )

    @staticmethod
    def _extract_label_value(lines: List[str], regex_patterns: List[str]) -> Optional[str]:
        """Searches lines for a regex pattern and returns the first group match."""
        for pattern in regex_patterns:
            compiled = re.compile(pattern, re.IGNORECASE)
            for line in lines:
                m = compiled.search(line)
                if m:
                    val = m.group(1).strip()
                    if val:
                        return val
        return None

    def _extract_tabular_line_items(self, lines: List[str]) -> Tuple[List[Dict[str, Any]], List[int]]:
        """
        Parses pipe-separated or whitespace-aligned line items, handling multi-line wrapped text.
        """
        items: List[Dict[str, Any]] = []
        table_line_indices: List[int] = []

        # Find header line containing keywords like Description / Item and Price / Total
        in_table = False
        delimiter = None

        for idx, line in enumerate(lines):
            # Check for table header
            lower_line = line.lower()
            if any(k in lower_line for k in ["item", "description", "particulars"]) and \
               any(k in lower_line for k in ["price", "amount", "rate", "total", "qty"]):
                in_table = True
                if "|" in line:
                    delimiter = "|"
                elif "\t" in line:
                    delimiter = "\t"
                continue

            # Check for end of table (totals keywords)
            if in_table and any(k in lower_line for k in ["subtotal", "sub-total", "grand total", "total tax", "taxes:", "tax:"]):
                break

            if in_table:
                # If pipe-delimited
                if delimiter == "|":
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    # Ignore separator dashes like '---'
                    if all(set(p) <= {"-", "=", " "} for p in parts):
                        continue
                    if len(parts) >= 3:
                        table_line_indices.append(idx)
                        parsed = self._parse_table_row_parts(parts)
                        if parsed:
                            items.append(parsed)
                    elif len(parts) == 1 and items:
                        # Wrapped description from previous row!
                        items[-1]["description"] += " " + parts[0]
                else:
                    # Whitespace / column alignment
                    parts = re.split(r"\s{2,}|\t", line)
                    parts = [p.strip() for p in parts if p.strip()]
                    if len(parts) >= 3:
                        table_line_indices.append(idx)
                        parsed = self._parse_table_row_parts(parts)
                        if parsed:
                            items.append(parsed)
                    elif len(parts) == 1 and items and not any(k in lower_line for k in ["total", "date", "subtotal"]):
                        # Description wrap
                        items[-1]["description"] += " " + parts[0]

        return items, table_line_indices

    @staticmethod
    def _parse_table_row_parts(parts: List[str]) -> Optional[Dict[str, Any]]:
        """
        Infers description, quantity, unit, price, and total from columns.
        Typical schemas:
        - [Description, Qty, Price, Total]
        - [Item, Qty, Unit, Price, Total]
        - [S.No, Description, Qty, Price, Total]
        """
        # If first column is serial number (e.g. 1, 2, 3), strip it
        if parts[0].isdigit() and len(parts) > 3:
            parts = parts[1:]

        if len(parts) == 3:
            # [Description, Qty, Total] or [Description, Price, Total]
            return {
                "description": parts[0],
                "quantity": parts[1],
                "unit": None,
                "unit_price": None,
                "line_total": parts[2],
            }
        elif len(parts) == 4:
            # [Description, Qty, Price, Total]
            return {
                "description": parts[0],
                "quantity": parts[1],
                "unit": None,
                "unit_price": parts[2],
                "line_total": parts[3],
            }
        elif len(parts) >= 5:
            # [Description, Qty, Unit, Price, Total]
            return {
                "description": parts[0],
                "quantity": parts[1],
                "unit": parts[2],
                "unit_price": parts[3],
                "line_total": parts[4],
            }
        return None
