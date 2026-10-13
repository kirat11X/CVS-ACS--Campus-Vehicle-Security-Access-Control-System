"""
Track B: Deterministic Financial Reconciliation Module.

Combines normalized invoice extractions with deterministic validation findings to
produce an auditable reconciliation state without mutating or fabricating extracted data.

Invariants:
- Never overwrite original extracted values when discrepancies are detected.
- Never invent missing totals to force mathematical agreement.
- Clearly flags invoices requiring human auditor intervention.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from .validation import DeterministicValidator, ReasonCode, ValidationFinding, ValidationSeverity


class ReconciliationStatus(str, Enum):
    """Categorical status of financial and structural reconciliation."""
    RECONCILED = "RECONCILED"
    RECONCILED_WITH_WARNINGS = "RECONCILED_WITH_WARNINGS"
    DISCREPANCY_FLAGGED = "DISCREPANCY_FLAGGED"
    CRITICAL_ARITHMETIC_FAILURE = "CRITICAL_ARITHMETIC_FAILURE"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"


class ReviewActionRecommendation(str, Enum):
    """Recommended action for human-in-the-loop review queue."""
    ACCEPT_CONFIDENT = "ACCEPT_CONFIDENT"
    QUEUE_FOR_HUMAN_REVIEW = "QUEUE_FOR_HUMAN_REVIEW"
    REJECT_INVALID_DATA = "REJECT_INVALID_DATA"


@dataclass(frozen=True)
class ReconciliationReport:
    """Immutable reconciliation summary attached to an extracted invoice."""
    document_id: str
    status: ReconciliationStatus
    recommendation: ReviewActionRecommendation
    findings: List[ValidationFinding]
    error_count: int
    warning_count: int
    critical_count: int
    requires_human_review: bool
    summary_message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "status": self.status.value,
            "recommendation": self.recommendation.value,
            "findings": [f.to_dict() for f in self.findings],
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "requires_human_review": self.requires_human_review,
            "summary_message": self.summary_message,
        }


class InvoiceReconciler:
    """
    Evaluates invoice consistency and produces reconciliation reports.
    """

    def __init__(self, validator: Optional[DeterministicValidator] = None):
        self.validator = validator or DeterministicValidator()

    def reconcile(self, invoice: Dict[str, Any], schema_valid: bool = True) -> ReconciliationReport:
        """
        Runs deterministic validation on an invoice and synthesizes the reconciliation report.
        """
        doc_id = str(invoice.get("document_id") or "unknown_doc")

        if not schema_valid:
            finding = ValidationFinding(
                code=ReasonCode.VAL_SCHEMA_VIOLATION,
                severity=ValidationSeverity.CRITICAL,
                field_or_line_id=None,
                expected_value="Valid against JSON schema",
                observed_value="Schema validation failed",
                difference=None,
                message="Invoice payload violated structural JSON schema constraints.",
                requires_human_review=True,
            )
            return ReconciliationReport(
                document_id=doc_id,
                status=ReconciliationStatus.SCHEMA_VALIDATION_ERROR,
                recommendation=ReviewActionRecommendation.REJECT_INVALID_DATA,
                findings=[finding],
                error_count=0,
                warning_count=0,
                critical_count=1,
                requires_human_review=True,
                summary_message="Document rejected: Schema validation failure.",
            )

        findings = self.validator.validate_invoice(invoice)

        critical_count = sum(1 for f in findings if f.severity == ValidationSeverity.CRITICAL)
        error_count = sum(1 for f in findings if f.severity == ValidationSeverity.ERROR)
        warning_count = sum(1 for f in findings if f.severity == ValidationSeverity.WARNING)

        # Determine overall reconciliation status
        if critical_count > 0:
            status = ReconciliationStatus.CRITICAL_ARITHMETIC_FAILURE
            recommendation = ReviewActionRecommendation.QUEUE_FOR_HUMAN_REVIEW
            summary = f"Critical arithmetic or total discrepancies detected ({critical_count} critical findings)."
            requires_human = True
        elif error_count > 0:
            status = ReconciliationStatus.DISCREPANCY_FLAGGED
            recommendation = ReviewActionRecommendation.QUEUE_FOR_HUMAN_REVIEW
            summary = f"Line arithmetic or subtotal discrepancies detected ({error_count} errors)."
            requires_human = True
        elif warning_count > 0:
            status = ReconciliationStatus.RECONCILED_WITH_WARNINGS
            recommendation = ReviewActionRecommendation.ACCEPT_CONFIDENT
            summary = f"Totals reconciled successfully with {warning_count} minor warnings."
            requires_human = any(f.requires_human_review for f in findings)
            if requires_human:
                recommendation = ReviewActionRecommendation.QUEUE_FOR_HUMAN_REVIEW
        else:
            status = ReconciliationStatus.RECONCILED
            recommendation = ReviewActionRecommendation.ACCEPT_CONFIDENT
            summary = "Invoice reconciled perfectly: all line items and totals agree."
            requires_human = False

        return ReconciliationReport(
            document_id=doc_id,
            status=status,
            recommendation=recommendation,
            findings=findings,
            error_count=error_count,
            warning_count=warning_count,
            critical_count=critical_count,
            requires_human_review=requires_human,
            summary_message=summary,
        )
