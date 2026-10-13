"""
Track B: End-to-End Invoice Processing Pipeline & Evaluation Harness.

Orchestrates document ingestion, schema validation, deterministic field normalization,
arithmetic verification, reconciliation reporting, and offline benchmark evaluations.

Invariants:
- Offline and strictly decoupled from production services.
- Never mutates extracted candidate data during reconciliation.
- Provides unified interface for batch evaluation across synthetic and future VLM corpora.
"""

from decimal import Decimal
import json
import os
import time
from typing import Any, Dict, List, Optional
import yaml

from .extraction_interface import DocumentReference, ExtractionResult
from .normalization import FieldNormalizer
from .validation import DeterministicValidator
from .reconciliation import InvoiceReconciler, ReconciliationStatus
from .baseline_extractor import DeterministicBaselineExtractor
from .evaluation import MetricCalculator, DocumentEvaluationSummary, BenchmarkAggregateSummary


class InvoicePipeline:
    """
    Offline end-to-end invoice parsing, reconciliation, and evaluation pipeline.
    """

    def __init__(
        self,
        extractor: Optional[DeterministicBaselineExtractor] = None,
        normalizer: Optional[FieldNormalizer] = None,
        validator: Optional[DeterministicValidator] = None,
        reconciler: Optional[InvoiceReconciler] = None,
        evaluator: Optional[MetricCalculator] = None,
    ):
        self.normalizer = normalizer or FieldNormalizer()
        self.validator = validator or DeterministicValidator()
        self.reconciler = reconciler or InvoiceReconciler(validator=self.validator)
        self.extractor = extractor or DeterministicBaselineExtractor(
            normalizer=self.normalizer,
            validator=self.validator,
            reconciler=self.reconciler
        )
        self.evaluator = evaluator or MetricCalculator()

    @classmethod
    def from_config(cls, config_path: str) -> "InvoicePipeline":
        """Factory constructor instantiating the pipeline from Track B's config.yaml."""
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        norm_cfg = cfg.get("normalization", {})
        normalizer = FieldNormalizer(
            default_currency=None,
            ambiguous_date_policy=norm_cfg.get("ambiguous_date_policy", "DAY_FIRST"),
            decimal_separator=norm_cfg.get("decimal_separator", "."),
            currency_map=norm_cfg.get("currency_symbols"),
            unit_map=norm_cfg.get("unit_aliases"),
        )

        val_cfg = cfg.get("validation", {})
        rounding_tol = Decimal(str(val_cfg.get("rounding_tolerance", "0.02")))
        tax_tol = Decimal(str(val_cfg.get("tax_calculation_tolerance", "0.05")))
        validator = DeterministicValidator(
            rounding_tolerance=rounding_tol,
            tax_tolerance=tax_tol,
        )

        reconciler = InvoiceReconciler(validator=validator)
        extractor = DeterministicBaselineExtractor(
            normalizer=normalizer,
            validator=validator,
            reconciler=reconciler,
        )

        eval_cfg = cfg.get("evaluation", {})
        eval_tol = Decimal(str(eval_cfg.get("tolerance_threshold", "0.05")))
        evaluator = MetricCalculator(
            line_item_similarity_threshold=float(eval_cfg.get("line_item_matching_threshold", 0.70)),
            numeric_tolerance=eval_tol,
        )

        return cls(
            extractor=extractor,
            normalizer=normalizer,
            validator=validator,
            reconciler=reconciler,
            evaluator=evaluator,
        )

    def process_document(self, doc_ref: DocumentReference, raw_text: str) -> ExtractionResult:
        """
        Processes a single invoice document through extraction and reconciliation.
        """
        return self.extractor.extract(doc_ref, raw_text)

    @staticmethod
    def load_json_fixtures(file_path: str) -> Any:
        """Loads JSON fixture files."""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate_corpus(
        self,
        invoices: List[Dict[str, Any]],
        ground_truth_map: Dict[str, Dict[str, Any]],
        benchmark_type: str = "synthetic_baseline",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BenchmarkAggregateSummary:
        """
        Runs batch evaluation across an invoice corpus and calculates aggregate performance.
        Each item in `invoices` is expected to have:
        - `document_id`: str
        - `raw_text`: str
        - `category`: str (optional, e.g. single_line, multi_line, rounding_diff)
        """
        doc_summaries: List[DocumentEvaluationSummary] = []

        for inv in invoices:
            doc_id = inv["document_id"]
            raw_text = inv.get("raw_text", "")
            category = inv.get("category", "standard")
            page_count = inv.get("page_count", 1)

            doc_ref = DocumentReference(document_id=doc_id, page_count=page_count)
            res = self.process_document(doc_ref, raw_text)

            gt = ground_truth_map.get(doc_id)
            if not gt:
                continue

            # Selected candidate invoice
            pred_invoice = res.candidates[0].invoice if res.candidates else {}
            schema_valid = (len(res.schema_validation_errors) == 0)
            reconciled = (res.reconciliation_status in [
                ReconciliationStatus.RECONCILED.value,
                ReconciliationStatus.RECONCILED_WITH_WARNINGS.value,
            ])

            summary = self.evaluator.evaluate_document(
                predicted=pred_invoice,
                ground_truth=gt,
                category=category,
                schema_valid=schema_valid,
                reconciled=reconciled,
                latency_ms=res.latency_ms,
            )
            doc_summaries.append(summary)

        meta = dict(metadata or {})
        meta["benchmark_type"] = benchmark_type
        meta["total_processed"] = len(doc_summaries)

        return self.evaluator.compute_aggregate_summary(
            doc_summaries,
            benchmark_type=benchmark_type,
            metadata=meta,
        )
