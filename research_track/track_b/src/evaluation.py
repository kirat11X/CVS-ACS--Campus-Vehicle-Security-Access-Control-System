"""
Track B: Offline Evaluation Metrics & Line-Item Alignment Module.

Computes comprehensive, mathematically rigorous offline evaluation metrics for
invoice extraction pipelines, including:
- Header-level Exact Match (Invoice number, Supplier name, Date, Currency)
- Bipartite Line-Item Alignment (Hungarian/Greedy matching)
- Line-Item Precision, Recall, and F1
- Decimal-Safe Numeric Matching (Exact and Tolerance-based)
- Complete-Invoice Exact Match
- Schema-Validity & Arithmetic Reconciliation Pass Rates
- Missing-Field Handling Accuracy & False Extraction Rates
- Latency Percentiles (P50, P90, P95, Mean)
- Categorical Disaggregation by Document Archetype

Invariants:
- Financial comparisons use decimal.Decimal (no binary float artifacts).
- Line items are paired strictly 1-to-1 without double counting.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
import math
from typing import Any, Dict, List, Optional, Set, Tuple


def token_similarity(s1: Optional[str], s2: Optional[str]) -> float:
    """Computes Jaccard word token similarity between two strings in [0.0, 1.0]."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    t1 = set(s1.upper().split())
    t2 = set(s2.upper().split())
    if not t1 or not t2:
        return 0.0
    intersection = len(t1 & t2)
    union = len(t1 | t2)
    return intersection / union if union > 0 else 0.0


@dataclass(frozen=True)
class LineItemAlignment:
    """A 1-to-1 pairing between an extracted line item and ground-truth line item."""
    pred_idx: int
    gt_idx: int
    pred_item: Dict[str, Any]
    gt_item: Dict[str, Any]
    similarity_score: float
    description_exact: bool
    quantity_exact: bool
    unit_price_exact: bool
    line_total_exact: bool
    line_total_within_tolerance: bool


@dataclass(frozen=True)
class DocumentEvaluationSummary:
    """Evaluation summary for a single invoice document comparison."""
    document_id: str
    category: str
    schema_valid: bool
    reconciled: bool
    complete_invoice_exact: bool
    invoice_number_exact: bool
    supplier_exact: bool
    date_exact: bool
    currency_exact: bool
    grand_total_exact: bool
    grand_total_within_tolerance: bool
    line_items_total_gt: int
    line_items_total_pred: int
    line_items_matched_tp: int
    line_item_precision: float
    line_item_recall: float
    line_item_f1: float
    missing_fields_accuracy: float
    false_extraction_count: int
    latency_ms: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "category": self.category,
            "schema_valid": self.schema_valid,
            "reconciled": self.reconciled,
            "complete_invoice_exact": self.complete_invoice_exact,
            "invoice_number_exact": self.invoice_number_exact,
            "supplier_exact": self.supplier_exact,
            "date_exact": self.date_exact,
            "currency_exact": self.currency_exact,
            "grand_total_exact": self.grand_total_exact,
            "grand_total_within_tolerance": self.grand_total_within_tolerance,
            "line_items_total_gt": self.line_items_total_gt,
            "line_items_total_pred": self.line_items_total_pred,
            "line_items_matched_tp": self.line_items_matched_tp,
            "line_item_precision": round(self.line_item_precision, 4),
            "line_item_recall": round(self.line_item_recall, 4),
            "line_item_f1": round(self.line_item_f1, 4),
            "missing_fields_accuracy": round(self.missing_fields_accuracy, 4),
            "false_extraction_count": self.false_extraction_count,
            "latency_ms": round(self.latency_ms, 2) if self.latency_ms is not None else None,
        }


@dataclass(frozen=True)
class BenchmarkAggregateSummary:
    """Aggregate benchmark metrics across a test corpus."""
    benchmark_type: str  # 'synthetic_baseline', 'public_benchmark', 'vlm_inference'
    total_documents: int
    schema_valid_rate: float
    reconciliation_pass_rate: float
    complete_invoice_exact_match_rate: float
    invoice_number_exact_rate: float
    supplier_exact_rate: float
    date_exact_rate: float
    currency_exact_rate: float
    grand_total_exact_rate: float
    grand_total_tolerance_rate: float
    mean_line_item_precision: float
    mean_line_item_recall: float
    mean_line_item_f1: float
    mean_missing_field_accuracy: float
    total_false_extractions: int
    latency_p50_ms: Optional[float]
    latency_p90_ms: Optional[float]
    latency_p95_ms: Optional[float]
    latency_mean_ms: Optional[float]
    category_breakdown: Dict[str, Dict[str, float]]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_type": self.benchmark_type,
            "total_documents": self.total_documents,
            "schema_valid_rate": round(self.schema_valid_rate, 4),
            "reconciliation_pass_rate": round(self.reconciliation_pass_rate, 4),
            "complete_invoice_exact_match_rate": round(self.complete_invoice_exact_match_rate, 4),
            "invoice_number_exact_rate": round(self.invoice_number_exact_rate, 4),
            "supplier_exact_rate": round(self.supplier_exact_rate, 4),
            "date_exact_rate": round(self.date_exact_rate, 4),
            "currency_exact_rate": round(self.currency_exact_rate, 4),
            "grand_total_exact_rate": round(self.grand_total_exact_rate, 4),
            "grand_total_tolerance_rate": round(self.grand_total_tolerance_rate, 4),
            "mean_line_item_precision": round(self.mean_line_item_precision, 4),
            "mean_line_item_recall": round(self.mean_line_item_recall, 4),
            "mean_line_item_f1": round(self.mean_line_item_f1, 4),
            "mean_missing_field_accuracy": round(self.mean_missing_field_accuracy, 4),
            "total_false_extractions": self.total_false_extractions,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p90_ms": self.latency_p90_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "latency_mean_ms": self.latency_mean_ms,
            "category_breakdown": self.category_breakdown,
            "metadata": self.metadata,
        }

    def format_markdown_table(self) -> str:
        """Renders aggregate metrics into GitHub-flavored markdown table."""
        lines = [
            f"### Benchmark Evaluation Summary (`{self.benchmark_type}`)",
            "",
            "| Metric | Rate / Value | Operational Interpretation |",
            "| :--- | :--- | :--- |",
            f"| **Evaluated Invoices** | {self.total_documents} | Total document corpus count |",
            f"| **Schema Valid Rate** | {self.schema_valid_rate * 100:.1f}% | Conforms to strict versioned JSON schema |",
            f"| **Arithmetic Pass Rate** | {self.reconciliation_pass_rate * 100:.1f}% | Passed deterministic balance reconciliation |",
            f"| **Complete Invoice Exact** | {self.complete_invoice_exact_match_rate * 100:.1f}% | 100% exact match across all headers, lines, totals |",
            f"| **Invoice Number Exact** | {self.invoice_number_exact_rate * 100:.1f}% | Exact billing identifier match |",
            f"| **Supplier Name Exact** | {self.supplier_exact_rate * 100:.1f}% | Normalized vendor string match |",
            f"| **Invoice Date Exact** | {self.date_exact_rate * 100:.1f}% | ISO date match |",
            f"| **Grand Total (Exact 0.00)** | {self.grand_total_exact_rate * 100:.1f}% | Decimal-exact monetary match |",
            f"| **Grand Total (Tol <= 0.05)**| {self.grand_total_tolerance_rate * 100:.1f}% | Match within standard rounding drift |",
            f"| **Line-Item Precision** | {self.mean_line_item_precision * 100:.1f}% | True positive items / total extracted items |",
            f"| **Line-Item Recall** | {self.mean_line_item_recall * 100:.1f}% | True positive items / ground-truth items |",
            f"| **Line-Item F1** | {self.mean_line_item_f1 * 100:.1f}% | Harmonic mean of item precision and recall |",
            f"| **Missing-Field Accuracy** | {self.mean_missing_field_accuracy * 100:.1f}% | Correct null handling for absent fields |",
            f"| **Total False Extractions**| {self.total_false_extractions} | Hallucinated values for absent fields |",
        ]
        if self.latency_mean_ms is not None:
            lines.extend([
                f"| **Mean Latency** | {self.latency_mean_ms:.1f} ms | Average extraction latency per document |",
                f"| **Latency P50 / P95** | {self.latency_p50_ms:.1f} / {self.latency_p95_ms:.1f} ms | Median and 95th percentile duration |",
            ])
        lines.append("")
        return "\n".join(lines)


class MetricCalculator:
    """
    Evaluator that aligns predicted extractions with ground-truth invoices
    and computes exact matches, tolerances, F1 scores, and error breakdowns.
    """

    def __init__(
        self,
        line_item_similarity_threshold: float = 0.70,
        numeric_tolerance: Decimal = Decimal("0.05")
    ):
        self.line_item_similarity_threshold = line_item_similarity_threshold
        self.numeric_tolerance = numeric_tolerance

    def evaluate_document(
        self,
        predicted: Dict[str, Any],
        ground_truth: Dict[str, Any],
        category: str = "standard",
        schema_valid: bool = True,
        reconciled: bool = True,
        latency_ms: Optional[float] = None
    ) -> DocumentEvaluationSummary:
        """
        Evaluates a single predicted invoice against ground-truth data.
        """
        doc_id = str(ground_truth.get("document_id") or predicted.get("document_id"))

        # 1. Header Exact Matches
        p_num = (predicted.get("invoice_number") or "").strip().upper()
        g_num = (ground_truth.get("invoice_number") or "").strip().upper()
        inv_num_exact = (p_num == g_num) if (p_num or g_num) else True

        p_supp = (predicted.get("supplier_name") or "").strip().upper()
        g_supp = (ground_truth.get("supplier_name") or "").strip().upper()
        supp_exact = (p_supp == g_supp) if (p_supp or g_supp) else True

        p_date = (predicted.get("invoice_date") or "").strip()
        g_date = (ground_truth.get("invoice_date") or "").strip()
        date_exact = (p_date == g_date) if (p_date or g_date) else True

        p_curr = (predicted.get("currency") or "").strip().upper()
        g_curr = (ground_truth.get("currency") or "").strip().upper()
        curr_exact = (p_curr == g_curr) if (p_curr or g_curr) else True

        # 2. Grand Total Decimal Checks
        p_totals = predicted.get("totals") or {}
        g_totals = ground_truth.get("totals") or {}
        p_gt_dec = self._to_decimal(p_totals.get("grand_total"))
        g_gt_dec = self._to_decimal(g_totals.get("grand_total"))

        if p_gt_dec is not None and g_gt_dec is not None:
            gt_exact = (p_gt_dec == g_gt_dec)
            gt_tol = (abs(p_gt_dec - g_gt_dec) <= self.numeric_tolerance)
        else:
            gt_exact = (p_gt_dec is None and g_gt_dec is None)
            gt_tol = gt_exact

        # 3. Line-Item Bipartite Alignment
        p_items = predicted.get("line_items") or []
        g_items = ground_truth.get("line_items") or []
        alignments = self.align_line_items(p_items, g_items)

        tp = len(alignments)
        fp = max(0, len(p_items) - tp)
        fn = max(0, len(g_items) - tp)

        prec = (tp / (tp + fp)) if (tp + fp) > 0 else (1.0 if not g_items else 0.0)
        rec = (tp / (tp + fn)) if (tp + fn) > 0 else (1.0 if not p_items else 0.0)
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else (1.0 if not g_items and not p_items else 0.0)

        # 4. Missing Field and False Extraction Checks
        # Verify fields that are None in ground truth are also None in predicted
        check_fields = ["invoice_number", "supplier_name", "invoice_date", "supplier_tax_id", "purchase_order_number"]
        absent_in_gt = [f for f in check_fields if not ground_truth.get(f)]
        correct_missing = sum(1 for f in absent_in_gt if not predicted.get(f))
        false_extractions = sum(1 for f in absent_in_gt if predicted.get(f))
        missing_acc = (correct_missing / len(absent_in_gt)) if absent_in_gt else 1.0

        # Complete invoice exact match
        all_lines_exact = (len(alignments) == len(g_items) == len(p_items)) and all(
            a.description_exact and a.quantity_exact and a.line_total_exact for a in alignments
        )
        complete_exact = (
            schema_valid and
            reconciled and
            inv_num_exact and
            supp_exact and
            date_exact and
            curr_exact and
            gt_exact and
            all_lines_exact
        )

        return DocumentEvaluationSummary(
            document_id=doc_id,
            category=category,
            schema_valid=schema_valid,
            reconciled=reconciled,
            complete_invoice_exact=complete_exact,
            invoice_number_exact=inv_num_exact,
            supplier_exact=supp_exact,
            date_exact=date_exact,
            currency_exact=curr_exact,
            grand_total_exact=gt_exact,
            grand_total_within_tolerance=gt_tol,
            line_items_total_gt=len(g_items),
            line_items_total_pred=len(p_items),
            line_items_matched_tp=tp,
            line_item_precision=prec,
            line_item_recall=rec,
            line_item_f1=f1,
            missing_fields_accuracy=missing_acc,
            false_extraction_count=false_extractions,
            latency_ms=latency_ms,
        )

    def align_line_items(
        self,
        pred_items: List[Dict[str, Any]],
        gt_items: List[Dict[str, Any]]
    ) -> List[LineItemAlignment]:
        """
        Optimal maximum-weight 1-to-1 bipartite matching between predicted and ground truth line items.
        Scores pairs based on description token overlap and line total agreement.
        When two pairings have identical scores, breaks ties deterministically using
        (predicted_index, ground_truth_index, description_lexicographical_order).
        Ensures strict 1-to-1 matching without double-counting.
        """
        candidates: List[Tuple[int, int, float, str, str]] = []

        for p_idx, p in enumerate(pred_items):
            p_desc = p.get("description") or p.get("normalized_description") or ""
            p_total = self._to_decimal(p.get("line_total"))

            for g_idx, g in enumerate(gt_items):
                g_desc = g.get("description") or g.get("normalized_description") or ""
                g_total = self._to_decimal(g.get("line_total"))

                desc_sim = token_similarity(p_desc, g_desc)

                # Bonus for exact or close line total
                price_bonus = 0.0
                if p_total is not None and g_total is not None:
                    if p_total == g_total:
                        price_bonus = 0.30
                    elif abs(p_total - g_total) <= self.numeric_tolerance:
                        price_bonus = 0.15

                composite_score = min(1.0, (desc_sim * 0.70) + price_bonus)
                if composite_score >= self.line_item_similarity_threshold:
                    candidates.append((p_idx, g_idx, composite_score, p_desc, g_desc))

        N = len(pred_items)
        M = len(gt_items)
        if N == 0 or M == 0 or not candidates:
            return []

        # Sort candidate edges deterministically to break ties:
        # (predicted_index, ground_truth_index, description_lexicographical_order)
        candidates.sort(
            key=lambda c: (
                c[0],
                c[1],
                (c[3] or "").strip().upper(),
                (c[4] or "").strip().upper(),
            )
        )
        total_candidates = len(candidates)

        weights: Dict[Tuple[int, int], float] = {}
        raw_scores: Dict[Tuple[int, int], float] = {}
        for rank, (p_idx, g_idx, score, _, _) in enumerate(candidates):
            # Infinitesimal deterministic tie-breaker preserving raw scores
            eps = (total_candidates - rank) * 1e-9
            weights[(p_idx, g_idx)] = score + eps
            raw_scores[(p_idx, g_idx)] = score

        # Kuhn-Munkres (Hungarian algorithm) for maximum weight bipartite matching on (N + M) x (N + M)
        K = N + M
        W = [[0.0] * K for _ in range(K)]
        for (i, j), w in weights.items():
            W[i][j] = w

        max_w = max([w for w in weights.values()] + [0.0])
        big = max_w + 1.0
        C = [[big - W[i][j] for j in range(K)] for i in range(K)]

        u = [0.0] * (K + 1)
        v = [0.0] * (K + 1)
        p = [0] * (K + 1)
        way = [0] * (K + 1)

        for i in range(1, K + 1):
            p[0] = i
            j0 = 0
            minv = [float("inf")] * (K + 1)
            used = [False] * (K + 1)
            while True:
                used[j0] = True
                i0 = p[j0]
                delta = float("inf")
                j1 = 0
                for j in range(1, K + 1):
                    if not used[j]:
                        cur = C[i0 - 1][j - 1] - u[i0] - v[j]
                        if cur < minv[j]:
                            minv[j] = cur
                            way[j] = j0
                        if minv[j] < delta:
                            delta = minv[j]
                            j1 = j
                for j in range(0, K + 1):
                    if used[j]:
                        u[p[j]] += delta
                        v[j] -= delta
                    else:
                        minv[j] -= delta
                j0 = j1
                if p[j0] == 0:
                    break
            while True:
                j1 = way[j0]
                p[j0] = p[j1]
                j0 = j1
                if j0 == 0:
                    break

        ans = [-1] * K
        for j in range(1, K + 1):
            if p[j] != 0:
                ans[p[j] - 1] = j - 1

        selected_pairs: List[Tuple[int, int, float]] = []
        for i in range(N):
            j = ans[i]
            if j < M and (i, j) in raw_scores:
                selected_pairs.append((i, j, raw_scores[(i, j)]))

        alignments: List[LineItemAlignment] = []
        for p_idx, g_idx, score in selected_pairs:
            p = pred_items[p_idx]
            g = gt_items[g_idx]

            p_desc = (p.get("description") or "").strip().upper()
            g_desc = (g.get("description") or "").strip().upper()

            p_qty = self._to_decimal(p.get("quantity"))
            g_qty = self._to_decimal(g.get("quantity"))

            p_price = self._to_decimal(p.get("unit_price"))
            g_price = self._to_decimal(g.get("unit_price"))

            p_total = self._to_decimal(p.get("line_total"))
            g_total = self._to_decimal(g.get("line_total"))

            total_exact = (p_total == g_total) if (p_total is not None and g_total is not None) else (p_total is None and g_total is None)
            total_tol = (abs(p_total - g_total) <= self.numeric_tolerance) if (p_total is not None and g_total is not None) else total_exact

            alignments.append(LineItemAlignment(
                pred_idx=p_idx,
                gt_idx=g_idx,
                pred_item=p,
                gt_item=g,
                similarity_score=score,
                description_exact=(p_desc == g_desc),
                quantity_exact=(p_qty == g_qty) if (p_qty is not None and g_qty is not None) else (p_qty is None and g_qty is None),
                unit_price_exact=(p_price == g_price) if (p_price is not None and g_price is not None) else (p_price is None and g_price is None),
                line_total_exact=total_exact,
                line_total_within_tolerance=total_tol,
            ))

        return alignments

    def compute_aggregate_summary(
        self,
        doc_summaries: List[DocumentEvaluationSummary],
        benchmark_type: str = "synthetic_baseline",
        metadata: Optional[Dict[str, Any]] = None
    ) -> BenchmarkAggregateSummary:
        """
        Aggregates document evaluations into corpus-wide metrics and category breakdowns.
        """
        n = len(doc_summaries)
        if n == 0:
            return BenchmarkAggregateSummary(
                benchmark_type=benchmark_type,
                total_documents=0,
                schema_valid_rate=0.0,
                reconciliation_pass_rate=0.0,
                complete_invoice_exact_match_rate=0.0,
                invoice_number_exact_rate=0.0,
                supplier_exact_rate=0.0,
                date_exact_rate=0.0,
                currency_exact_rate=0.0,
                grand_total_exact_rate=0.0,
                grand_total_tolerance_rate=0.0,
                mean_line_item_precision=0.0,
                mean_line_item_recall=0.0,
                mean_line_item_f1=0.0,
                mean_missing_field_accuracy=0.0,
                total_false_extractions=0,
                latency_p50_ms=None,
                latency_p90_ms=None,
                latency_p95_ms=None,
                latency_mean_ms=None,
                category_breakdown={},
                metadata=metadata or {},
            )

        # Categorical breakdowns
        categories: Set[str] = {d.category for d in doc_summaries}
        cat_breakdown: Dict[str, Dict[str, float]] = {}

        for cat in categories:
            cat_docs = [d for d in doc_summaries if d.category == cat]
            cn = len(cat_docs)
            cat_breakdown[cat] = {
                "count": float(cn),
                "complete_exact_rate": sum(1 for d in cat_docs if d.complete_invoice_exact) / cn,
                "reconciliation_pass_rate": sum(1 for d in cat_docs if d.reconciled) / cn,
                "grand_total_exact_rate": sum(1 for d in cat_docs if d.grand_total_exact) / cn,
                "line_item_f1": sum(d.line_item_f1 for d in cat_docs) / cn,
            }

        # Latencies
        lats = [d.latency_ms for d in doc_summaries if d.latency_ms is not None]
        p50 = None
        p90 = None
        p95 = None
        mean_lat = None
        if lats:
            lats.sort()
            ln = len(lats)
            p50 = lats[int(ln * 0.50)]
            p90 = lats[min(int(ln * 0.90), ln - 1)]
            p95 = lats[min(int(ln * 0.95), ln - 1)]
            mean_lat = sum(lats) / ln

        return BenchmarkAggregateSummary(
            benchmark_type=benchmark_type,
            total_documents=n,
            schema_valid_rate=sum(1 for d in doc_summaries if d.schema_valid) / n,
            reconciliation_pass_rate=sum(1 for d in doc_summaries if d.reconciled) / n,
            complete_invoice_exact_match_rate=sum(1 for d in doc_summaries if d.complete_invoice_exact) / n,
            invoice_number_exact_rate=sum(1 for d in doc_summaries if d.invoice_number_exact) / n,
            supplier_exact_rate=sum(1 for d in doc_summaries if d.supplier_exact) / n,
            date_exact_rate=sum(1 for d in doc_summaries if d.date_exact) / n,
            currency_exact_rate=sum(1 for d in doc_summaries if d.currency_exact) / n,
            grand_total_exact_rate=sum(1 for d in doc_summaries if d.grand_total_exact) / n,
            grand_total_tolerance_rate=sum(1 for d in doc_summaries if d.grand_total_within_tolerance) / n,
            mean_line_item_precision=sum(d.line_item_precision for d in doc_summaries) / n,
            mean_line_item_recall=sum(d.line_item_recall for d in doc_summaries) / n,
            mean_line_item_f1=sum(d.line_item_f1 for d in doc_summaries) / n,
            mean_missing_field_accuracy=sum(d.missing_fields_accuracy for d in doc_summaries) / n,
            total_false_extractions=sum(d.false_extraction_count for d in doc_summaries),
            latency_p50_ms=p50,
            latency_p90_ms=p90,
            latency_p95_ms=p95,
            latency_mean_ms=mean_lat,
            category_breakdown=cat_breakdown,
            metadata=metadata or {},
        )

    @staticmethod
    def _to_decimal(val: Any) -> Optional[Decimal]:
        """Safely parses val into Decimal."""
        if val is None:
            return None
        if isinstance(val, Decimal):
            return val
        try:
            return Decimal(str(val).strip())
        except Exception:
            return None
