"""
Track B: Invoice Document Parsing and Line-Item Extraction Research Prototype.
"""

from .normalization import FieldNormalizer, NormalizedMoney
from .validation import DeterministicValidator, ValidationFinding, ValidationSeverity, ReasonCode
from .reconciliation import InvoiceReconciler, ReconciliationStatus, ReconciliationReport, ReviewActionRecommendation
from .extraction_interface import (
    DocumentReference,
    ExtractionCandidate,
    ExtractionResult,
    InvoiceExtractor,
    SchemaValidator,
)
from .baseline_extractor import DeterministicBaselineExtractor
from .evaluation import (
    MetricCalculator,
    DocumentEvaluationSummary,
    BenchmarkAggregateSummary,
    LineItemAlignment,
)
from .pipeline import InvoicePipeline

__all__ = [
    "FieldNormalizer",
    "NormalizedMoney",
    "DeterministicValidator",
    "ValidationFinding",
    "ValidationSeverity",
    "ReasonCode",
    "InvoiceReconciler",
    "ReconciliationStatus",
    "ReconciliationReport",
    "ReviewActionRecommendation",
    "DocumentReference",
    "ExtractionCandidate",
    "ExtractionResult",
    "InvoiceExtractor",
    "SchemaValidator",
    "DeterministicBaselineExtractor",
    "MetricCalculator",
    "DocumentEvaluationSummary",
    "BenchmarkAggregateSummary",
    "LineItemAlignment",
    "InvoicePipeline",
]
