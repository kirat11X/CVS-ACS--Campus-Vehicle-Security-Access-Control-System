# Track B: Invoice Line-Item Extraction Research Prototype

Standalone, additive-only research prototype for document parsing, line-item extraction, and deterministic financial reconciliation for the PEC Chandigarh Campus Vehicle Security & Access-Control System.

---

## 1. Directory Structure

```text
research_track/track_b/
├── config.yaml                     # Pipeline parameters, normalization rules, and validation tolerances
├── schemas/
│   ├── invoice_schema.json         # Strict versioned JSON schema for parsed invoices
│   └── extraction_result_schema.json # Schema for candidate extractions and validation findings
├── src/
│   ├── __init__.py                 # Public package exports
│   ├── normalization.py            # Decimal-safe currency parsing, ISO dates, unit normalization
│   ├── validation.py               # Deterministic arithmetic validation (lines, subtotals, grand totals)
│   ├── reconciliation.py           # Financial reconciliation state machine and audit reports
│   ├── extraction_interface.py     # Model-independent extraction ABC and schema pre-validator
│   ├── baseline_extractor.py       # Deterministic regex and tabular text extractor
│   ├── evaluation.py               # Line-item bipartite matching, precision/recall/F1, and metrics
│   └── pipeline.py                 # End-to-end InvoicePipeline and evaluation harness
├── fixtures/
│   ├── synthetic_invoices.json     # 32 synthetic invoice texts spanning 10+ operational categories
│   ├── synthetic_ground_truth.json # Ground-truth JSON annotations for all 32 synthetic invoices
│   └── adversarial_cases.json      # 6 adversarial test cases (tampered math, inverted tax, spoofing)
├── tests/
│   └── test_cases.md               # Complete test case matrix across all 38 fixtures
├── reports/
│   └── EVALUATION_PLAN.md          # Future VLM and benchmark comparison protocol (Baselines A-B, Candidates C-F)
├── SPECIFICATION.md                # Full technical specification, data contracts, and invariants
├── IMPLEMENTATION_REPORT.md        # Comprehensive implementation and asset discovery audit report
├── results/
│   └── .gitkeep                    # Destination directory for deferred offline evaluation outputs
└── README.md                       # This documentation file
```

---

## 2. Core Architectural Principles

### 2.1 Decimal-Safe Monetary Arithmetic
Binary floating-point types (`float`) introduce precision drift (e.g. `0.1 + 0.2 = 0.30000000000000004`). All monetary parsing, line calculations, tax rates, and total comparisons in Track B strictly utilize Python `decimal.Decimal` and string representations adhering to `^-?[0-9]+(\.[0-9]+)?$`.

### 2.2 Non-Destructive Reconciliation
Validation is diagnostic. When a subtotal mismatch or calculation error is detected, the pipeline **never overwrites or mutates** the extracted values to force totals to balance. Discrepancies are logged as immutable `ValidationFinding` objects, and the invoice is flagged for human review.

### 2.3 Decoupling Extraction from Security Policy (Track C)
Track B extracts what a receipt or invoice claims (supplier, dates, quantities, prices, descriptions). It **does not** screen items into restricted campus categories (`TOBACCO_NICOTINE`, `ALCOHOL`, etc.) or make security decisions. Item categorization belongs strictly to Track C.

---

## 3. Supported Formats & Baseline Limitations

`DeterministicBaselineExtractor` supports documented synthetic structured text:
- **Header Metadata**: Label-value pairs (`Invoice #:`, `Date:`, `Supplier:`, `Currency:`, `PO #:`, `Tax ID:`).
- **Tabular Items**: Column-aligned or pipe-separated (`|`) tables with `Item | Qty | Unit | Price | Total`.
- **Description Continuation**: Handles wrapped descriptions spanning subsequent lines without quantities.
- **Explicit Limitations**: Does not process scanned visual image PDFs, handwritten receipts, or non-tabular natural language text without an upstream OCR or VLM engine.

---

## 4. Evaluation Metrics & Line-Item Alignment

- **Bipartite Line-Item Alignment**: Aligns predicted and ground-truth line items using token overlap and price proximity without double-counting.
- **Precision, Recall, F1**: Measures item extraction fidelity.
- **Monetary Match**: Evaluated both as **Exact Match** ($\Delta = 0.00$) and **Tolerance Match** ($\Delta \le 0.05$).
- **Reconciliation Pass Rate**: Proportion of invoices that achieve mathematical balance across all lines and totals.
- **Missing-Field Accuracy**: Verifies that absent fields correctly return `null` rather than hallucinated text.

---

## 5. Deferred Execution Instructions

In accordance with user safety rules, **zero code or tests have been executed during development**. When ready to execute offline benchmarks on a dedicated CPU environment:

```bash
# 1. Activate isolated Python 3.12 ML virtual environment
source ~/ml-assets/campus/.venv-ml/bin/activate

# 2. Run offline evaluation harness across synthetic corpus
python -c "
from research_track.track_b.src.pipeline import InvoicePipeline
pipe = InvoicePipeline.from_config('research_track/track_b/config.yaml')
invoices = pipe.load_json_fixtures('research_track/track_b/fixtures/synthetic_invoices.json')
gt_map = pipe.load_json_fixtures('research_track/track_b/fixtures/synthetic_ground_truth.json')

summary = pipe.evaluate_corpus(invoices, gt_map, benchmark_type='synthetic_baseline')
print(summary.format_markdown_table())
"
```

---

## 6. Synthetic Data Disclosure

All 32 invoice fixtures and 6 adversarial test cases are synthetic, generated with fictional company names, simulated campus grocery items, and artificial financial values. No actual commercial records, personal data, or real financial identifiers are included.
