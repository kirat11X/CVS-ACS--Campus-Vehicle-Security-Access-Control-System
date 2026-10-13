"""
Track B: Model-Independent Invoice Extraction Interface.

Defines the abstract contracts, candidate representations, document references,
and pre-reconciliation schema validation rules for invoice extractors.

Invariants:
- Strictly decoupled from FastAPI, n8n, PostgreSQL, and external services.
- Model outputs are untrusted until validated against the strict JSON schema.
- Rejects malformed JSON and unexpected shapes rather than silently repairing them.
- Prevents any tool execution or external side effects from model outputs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator, FormatChecker


@dataclass(frozen=True)
class DocumentReference:
    """Immutable reference to an invoice document, scan, or text artifact."""
    document_id: str
    file_path: Optional[str] = None
    page_count: Optional[int] = None
    mime_type: str = "text/plain"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionCandidate:
    """A single structured invoice hypothesis produced by an extractor."""
    candidate_id: str
    invoice: Dict[str, Any]
    ranking_score: float = 1.0
    rationale: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "ranking_score": round(self.ranking_score, 4),
            "invoice": self.invoice,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ExtractionResult:
    """Standardized output returned by any invoice extraction implementation."""
    schema_version: str
    document_id: str
    extractor_name: str
    extractor_version: str
    execution_timestamp: Optional[str]
    latency_ms: Optional[float]
    candidates: List[ExtractionCandidate]
    selected_candidate_id: Optional[str]
    reconciliation_status: str
    requires_human_review: bool
    validation_findings: List[Dict[str, Any]]
    schema_validation_errors: List[str]
    raw_output: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
            "execution_timestamp": self.execution_timestamp,
            "latency_ms": round(self.latency_ms, 2) if self.latency_ms is not None else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "selected_candidate_id": self.selected_candidate_id,
            "reconciliation_status": self.reconciliation_status,
            "requires_human_review": self.requires_human_review,
            "validation_findings": self.validation_findings,
            "schema_validation_errors": self.schema_validation_errors,
            "raw_output": self.raw_output,
        }


class SchemaValidator:
    """
    Validates candidate invoice representations against the strict structural JSON schema.
    Provides structural verification with zero external runtime dependencies.
    """

    @classmethod
    def validate_invoice_dict(cls, data: Any) -> Tuple[bool, List[str]]:
        """
        Validates an extracted invoice dictionary against required structure and types.
        """
        if not isinstance(data, dict):
            return False, ["Root invoice payload must be a JSON object / dict."]

        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "invoice_schema.json"
        with schema_path.open("r", encoding="utf-8") as schema_file:
            schema = json.load(schema_file)

        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
        return not errors, [f"{list(error.absolute_path)}: {error.message}" for error in errors]


class InvoiceExtractor(ABC):
    """
    Abstract Base Class for invoice document parsing and line-item extraction.
    Future implementations:
    - DeterministicBaselineExtractor (provided)
    - DonutDocumentExtractor (deferred)
    - QwenVLDocumentExtractor (deferred)
    - GroundTruthExtractor (testing)
    """

    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    @abstractmethod
    def extract(self, doc_ref: DocumentReference, raw_content: Any) -> ExtractionResult:
        """
        Parses document content into an auditable ExtractionResult containing candidates.
        """
        raise NotImplementedError

    def validate_candidate(self, invoice_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validates candidate extraction against strict schema rules."""
        return SchemaValidator.validate_invoice_dict(invoice_dict)
