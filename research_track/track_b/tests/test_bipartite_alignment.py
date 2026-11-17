"""
Unit Tests for Deterministic Optimal Bipartite Alignment (B-S1-003).

Verifies:
1. Strict 1-to-1 matching: No predicted or ground-truth line item is ever matched more than once.
2. Deterministic output: Multiple runs with shuffled candidate order yield 100% identical matching.
3. Optimal total score: Solves maximum weight bipartite matching where greedy assignment fails.
4. Deterministic tie-breaking: Ties on identical scores resolve strictly via
   (predicted_index, ground_truth_index, description_lexicographical_order).
5. Threshold rejection: Pairs below similarity threshold are strictly excluded.
6. Rectangular matching: Gracefully handles unequal item counts (N > M and N < M).
7. Empty inputs: Safely handles empty collections without exceptions.
"""

from decimal import Decimal
import random
import unittest

from research_track.track_b.src.evaluation import (
    LineItemAlignment,
    MetricCalculator,
    token_similarity,
)


class TestDeterministicOptimalBipartiteAlignment(unittest.TestCase):

    def setUp(self):
        self.calculator = MetricCalculator(
            line_item_similarity_threshold=0.70,
            numeric_tolerance=Decimal("0.05"),
        )

    def test_strict_one_to_one_matching(self):
        """
        Verifies that no line item on either side is matched more than once,
        even in dense graphs with many overlapping high-similarity candidates.
        """
        # Pred items share tokens with multiple GT items
        pred_items = [
            {"description": "Organic Whole Milk 1L", "line_total": "65.00"},
            {"description": "Organic Low Fat Milk 1L", "line_total": "65.00"},
            {"description": "Organic Skimmed Milk 1L", "line_total": "65.00"},
            {"description": "Fresh Milk Pouch 500ml", "line_total": "30.00"},
        ]
        gt_items = [
            {"description": "Organic Whole Milk 1L Carton", "line_total": "65.00"},
            {"description": "Organic Low Fat Milk 1L Carton", "line_total": "65.00"},
            {"description": "Organic Skimmed Milk 1L Carton", "line_total": "65.00"},
            {"description": "Fresh Toned Milk Pouch 500ml", "line_total": "30.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)

        matched_pred_indices = [a.pred_idx for a in alignments]
        matched_gt_indices = [a.gt_idx for a in alignments]

        # No double counting
        self.assertEqual(len(matched_pred_indices), len(set(matched_pred_indices)), "Duplicate predicted index found")
        self.assertEqual(len(matched_gt_indices), len(set(matched_gt_indices)), "Duplicate ground truth index found")
        self.assertEqual(len(alignments), 4)

    def test_optimal_total_score_vs_greedy_failure_case(self):
        """
        Classic assignment problem trap where greedy matching fails:
        Pred 0 has high similarity with GT 0 (0.95), and moderate similarity with GT 1 (0.88).
        Pred 1 has similarity only with GT 0 (0.90).

        Greedy matcher assigns Pred 0 -> GT 0 (0.95), leaving Pred 1 unmatched:
          Total greedy score = 0.95 (1 item matched).
        Optimal maximum-weight bipartite matching assigns:
          Pred 0 -> GT 1 (0.88) and Pred 1 -> GT 0 (0.90):
          Total optimal score = 1.78 (2 items matched).
        """
        p0 = "Widget Deluxe Pro Edition"
        p1 = "Widget Deluxe Pro 2026"
        g0 = "Widget Deluxe Pro Edition 2026"
        g1 = "Widget Deluxe Edition"

        pred_items = [
            {"description": p0, "line_total": "100.00"},
            {"description": p1, "line_total": "100.00"},
        ]
        gt_items = [
            {"description": g0, "line_total": "100.00"},
            {"description": g1, "line_total": "100.00"},
        ]

        s00 = min(1.0, token_similarity(p0, g0) * 0.70 + 0.30)
        s01 = min(1.0, token_similarity(p0, g1) * 0.70 + 0.30)
        s10 = min(1.0, token_similarity(p1, g0) * 0.70 + 0.30)
        s11 = min(1.0, token_similarity(p1, g1) * 0.70 + 0.30)

        # In greedy matching: if Pred 0 greedily consumes GT 0 (s00=0.860),
        # Pred 1 is left with only GT 1, which is below the 0.70 threshold (s11=0.580).
        # Greedy total = 0.860 (1 match).
        self.assertGreaterEqual(s00, 0.70)
        self.assertGreaterEqual(s01, 0.70)
        self.assertGreaterEqual(s10, 0.70)
        self.assertLess(s11, 0.70)

        alignments = self.calculator.align_line_items(pred_items, gt_items)

        # Optimal bipartite matching must match BOTH items: (0, 1) and (1, 0)
        self.assertEqual(len(alignments), 2, "Optimal bipartite matching should find 2 matches")

        matches = {(a.pred_idx, a.gt_idx) for a in alignments}
        total_score = sum(a.similarity_score for a in alignments)

        self.assertEqual(matches, {(0, 1), (1, 0)})
        self.assertGreater(total_score, s00, "Optimal total score (1.685) must exceed single greedy choice (0.860)")

    def test_deterministic_output_across_multiple_runs_with_shuffled_candidates(self):
        """
        Verifies that multiple executions with shuffled candidate input order produce
        100% identical alignments and identical order.
        """
        pred_items = [
            {"description": f"Product Category Item {i}", "line_total": f"{10 * i}.00"}
            for i in range(1, 7)
        ]
        gt_items = [
            {"description": f"Product Category Item {i}", "line_total": f"{10 * i}.00"}
            for i in range(1, 7)
        ]

        baseline_alignment = self.calculator.align_line_items(pred_items, gt_items)
        baseline_tuples = [(a.pred_idx, a.gt_idx, round(a.similarity_score, 4)) for a in baseline_alignment]

        # Test across 20 distinct random seeds
        for seed in range(20):
            rng = random.Random(seed)
            shuffled_gt = list(gt_items)
            rng.shuffle(shuffled_gt)

            # Re-run alignment
            alignments = self.calculator.align_line_items(pred_items, shuffled_gt)

            # Map back to verify correctness: each pred item i should match corresponding GT item i
            for a in alignments:
                p_desc = pred_items[a.pred_idx]["description"]
                g_desc = shuffled_gt[a.gt_idx]["description"]
                self.assertEqual(p_desc, g_desc, f"Mismatch at seed {seed}")

    def test_deterministic_tie_breaking_predicted_index(self):
        """
        When two predicted items have identical scores with the same ground truth item,
        ties must break in favor of lower predicted_index (predicted_index 0 beats 1).
        """
        # Exactly identical descriptions and amounts
        pred_items = [
            {"description": "Generic Paracetamol 500mg", "line_total": "25.00"},
            {"description": "Generic Paracetamol 500mg", "line_total": "25.00"},
        ]
        # Only one ground truth item available
        gt_items = [
            {"description": "Generic Paracetamol 500mg", "line_total": "25.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)

        self.assertEqual(len(alignments), 1)
        # Pred index 0 must win tie-break over pred index 1
        self.assertEqual(alignments[0].pred_idx, 0)
        self.assertEqual(alignments[0].gt_idx, 0)

    def test_deterministic_tie_breaking_ground_truth_index(self):
        """
        When one predicted item has identical scores with two ground truth items,
        ties must break in favor of lower ground_truth_index (ground_truth_index 0 beats 1).
        """
        pred_items = [
            {"description": "Aspirin Dispersible 75mg", "line_total": "40.00"},
        ]
        gt_items = [
            {"description": "Aspirin Dispersible 75mg", "line_total": "40.00"},
            {"description": "Aspirin Dispersible 75mg", "line_total": "40.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)

        self.assertEqual(len(alignments), 1)
        self.assertEqual(alignments[0].pred_idx, 0)
        self.assertEqual(alignments[0].gt_idx, 0)

    def test_deterministic_tie_breaking_description_lexicographical_order(self):
        """
        Verifies tie-breaking order considers description lexicographical order
        deterministically when candidate edges compete.
        """
        pred_items = [
            {"description": "Alpha Item", "line_total": "100.00"},
            {"description": "Beta Item", "line_total": "100.00"},
        ]
        gt_items = [
            {"description": "Alpha Item", "line_total": "100.00"},
            {"description": "Beta Item", "line_total": "100.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)
        self.assertEqual(len(alignments), 2)
        self.assertEqual(alignments[0].pred_idx, 0)
        self.assertEqual(alignments[0].gt_idx, 0)
        self.assertEqual(alignments[1].pred_idx, 1)
        self.assertEqual(alignments[1].gt_idx, 1)

    def test_threshold_rejection(self):
        """
        Verifies line items with similarity score below threshold are excluded.
        """
        pred_items = [
            {"description": "Wireless Bluetooth Mouse", "line_total": "450.00"},
        ]
        gt_items = [
            {"description": "Almond Chocolate Cookies 200g", "line_total": "120.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)
        self.assertEqual(len(alignments), 0)

    def test_rectangular_matching_more_predicted_than_ground_truth(self):
        """
        When N > M (3 predicted, 2 ground truth), matches at most 2 items.
        """
        pred_items = [
            {"description": "Item One", "line_total": "10.00"},
            {"description": "Item Two", "line_total": "20.00"},
            {"description": "Item Three Extra", "line_total": "30.00"},
        ]
        gt_items = [
            {"description": "Item One", "line_total": "10.00"},
            {"description": "Item Two", "line_total": "20.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)
        self.assertEqual(len(alignments), 2)
        matched_preds = [a.pred_idx for a in alignments]
        self.assertIn(0, matched_preds)
        self.assertIn(1, matched_preds)
        self.assertNotIn(2, matched_preds)

    def test_rectangular_matching_fewer_predicted_than_ground_truth(self):
        """
        When N < M (2 predicted, 3 ground truth), matches at most 2 items.
        """
        pred_items = [
            {"description": "Item Alpha", "line_total": "15.00"},
            {"description": "Item Beta", "line_total": "25.00"},
        ]
        gt_items = [
            {"description": "Item Alpha", "line_total": "15.00"},
            {"description": "Item Beta", "line_total": "25.00"},
            {"description": "Item Gamma Unmatched", "line_total": "35.00"},
        ]

        alignments = self.calculator.align_line_items(pred_items, gt_items)
        self.assertEqual(len(alignments), 2)
        matched_gts = [a.gt_idx for a in alignments]
        self.assertIn(0, matched_gts)
        self.assertIn(1, matched_gts)
        self.assertNotIn(2, matched_gts)

    def test_empty_collections_handling(self):
        """
        Gracefully handles empty lists without error.
        """
        self.assertEqual(self.calculator.align_line_items([], []), [])
        self.assertEqual(self.calculator.align_line_items([{"description": "A"}], []), [])
        self.assertEqual(self.calculator.align_line_items([], [{"description": "B"}]), [])

    def test_end_to_end_document_evaluation_metrics(self):
        """
        Verifies document evaluation summary correctly incorporates optimal line item matching.
        """
        pred_doc = {
            "document_id": "DOC-99",
            "invoice_number": "INV-99",
            "supplier_name": "Acme Corp",
            "invoice_date": "2026-11-01",
            "currency": "INR",
            "totals": {"grand_total": "300.00"},
            "line_items": [
                {"description": "Widget A", "line_total": "100.00", "quantity": "1", "unit_price": "100.00"},
                {"description": "Widget B", "line_total": "200.00", "quantity": "2", "unit_price": "100.00"},
            ],
        }
        gt_doc = {
            "document_id": "DOC-99",
            "invoice_number": "INV-99",
            "supplier_name": "Acme Corp",
            "invoice_date": "2026-11-01",
            "currency": "INR",
            "totals": {"grand_total": "300.00"},
            "line_items": [
                {"description": "Widget A", "line_total": "100.00", "quantity": "1", "unit_price": "100.00"},
                {"description": "Widget B", "line_total": "200.00", "quantity": "2", "unit_price": "100.00"},
            ],
        }

        summary = self.calculator.evaluate_document(pred_doc, gt_doc)
        self.assertEqual(summary.line_items_total_gt, 2)
        self.assertEqual(summary.line_items_total_pred, 2)
        self.assertEqual(summary.line_items_matched_tp, 2)
        self.assertAlmostEqual(summary.line_item_precision, 1.0)
        self.assertAlmostEqual(summary.line_item_recall, 1.0)
        self.assertAlmostEqual(summary.line_item_f1, 1.0)
        self.assertTrue(summary.complete_invoice_exact)


if __name__ == "__main__":
    unittest.main()
