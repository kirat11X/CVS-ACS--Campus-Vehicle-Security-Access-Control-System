# Track B: Future Model Comparison & Benchmark Evaluation Plan

This document establishes the experimental protocol, public dataset mappings, architectural lineage checks, and licensing constraints for future empirical evaluations of invoice extraction models for the PEC Chandigarh Campus Vehicle Security System.

---

## 1. Executive Summary & Experimental Scope

Track B evaluates the evolution from deterministic rule-based text parsers to state-of-the-art multimodal vision-language models (VLMs) and specialized document transformer architectures:

```
[Baseline A: Deterministic Text Parser]
               │
               ▼
[Baseline B: OCR + Spatial Heuristics (Tesseract/PaddleOCR + Rules)]
               │
               ▼
[Candidate C: Document Transformer (Donut-style End-to-End)]
               │
               ▼
[Candidate D: Base VLM (Qwen3-VL-2B-Instruct)]
               │
               ▼
[Candidate E: Scaled VLM (Qwen2.5-VL-3B-Instruct)]
               │
               ▼
[Candidate F: Specialized Adapters (Qwen3-VL-2B + Receipt LoRA)]
```

---

## 2. Asset Discovery & Environmental Verification Audit

An inspection of the local filesystem under `~/ml-assets/campus/` reveals:
- **Discovered On Disk**: Cloned repository `code/Indian_LPR/` (Track A reference).
- **Not Present Locally**: Heavyweight models (`Qwen/Qwen3-VL-2B-Instruct`, `systemk-ai/Qwen3-VL-2B-Instruct-receipt-lora`, etc.) and public datasets (`invoices-donut-data-v1`, `naver-clova-ix/cord-v2`) listed in `SETUP_RESULT.md` are currently **absent** from the local storage volume.
- **Experimental Blocker**: Empirical benchmark execution of Candidates C through F is formally blocked until model weights and dataset shards are downloaded to `~/ml-assets/campus/` without exceeding the 30 GB disk ceiling.
- **Zero Execution Invariant**: In accordance with project safety rules, **zero model inference, weights downloading, or GPU initialization was performed**.

---

## 3. Evaluated Architectures & Model Compatibility Analysis

| Candidate ID | Model Identifier | Base Architecture | Intended Role | License | Hardware Requirements | Compatibility / Lineage Check |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline A** | `deterministic_baseline_v1` | Regex / Python String Heuristics | Fast structured text baseline | Apache-2.0 | CPU only (<10 MB RAM, <2 ms) | Fully implemented in `src/baseline_extractor.py`. |
| **Baseline B** | `ocr_rules_pipeline` | OCR engine + Table Grid segmenter | Scanned image baseline | Apache-2.0 | CPU / Low-end GPU (1-2 GB VRAM) | Requires external OCR token bounding boxes. |
| **Candidate C** | `donut_invoice_v1` | Swin Transformer + mBART | Specialized document OCR-free parser | MIT | 4-6 GB VRAM, fp16 | Directly outputs XML/JSON tokens without OCR. |
| **Candidate D** | `Qwen3-VL-2B-Instruct` | Qwen3 Vision-Language Model (2B) | General multimodal invoice extraction | Apache-2.0 | 6-8 GB VRAM, int4/fp16 | Foundation VLM. Strong multilingual reasoning. |
| **Candidate E** | `Qwen2.5-VL-3B-Instruct` | Qwen2.5 Vision-Language Model (3B) | Scaled multimodal extraction | Qwen Research (Research Only) | 8-10 GB VRAM, int4 | **Blocker**: Research-only terms; skipped in staging. |
| **Candidate F** | `systemk-ai/Qwen3-VL-2B-receipt-lora` | LoRA Adapter (rank=16) on Qwen3-VL-2B | Fine-tuned receipt key-value extraction | Apache-2.0 | 6-8 GB VRAM | **Critical Lineage Check**: Trained specifically on POS receipts. May fail on full A4 tax invoices. |

### Adapter Compatibility Warnings
1. **Receipt LoRAs vs Complex Tax Invoices**: The staged adapter references (`systemk-ai`, `chai1me`, `saliousk`) were trained on receipt benchmarks (CORD / SROIE). POS receipts have vertical roll formats and flat single-tax rates. They do **not** generalize trivially to Indian GST invoices featuring HSN/SAC codes, multi-slab CGST/SGST/IGST breakdowns, and multi-page transport bilties.
2. **Base Model Lineage Verification**: LoRA weights for `Qwen2-VL` cannot be mounted onto `Qwen3-VL` base models due to structural transformer attention dimension divergences. Each adapter must match its exact base model commit hash.

---

## 4. Public Dataset Benchmarks & Field Mappings

### A. CORD-v2 (`naver-clova-ix/cord-v2`)
- **License**: CC-BY-4.0 (Commercial and research permitted with attribution).
- **Format**: Hierarchical food and retail receipts with bounding box polygons.
- **Field Mapping to Track B**:
  - `menu.nm` $\rightarrow$ `line_item.description`
  - `menu.cnt` $\rightarrow$ `line_item.quantity`
  - `menu.unitprice` $\rightarrow$ `line_item.unit_price`
  - `menu.price` $\rightarrow$ `line_item.line_total`
  - `sub_total.subtotal_price` $\rightarrow$ `totals.subtotal`
  - `total.total_price` $\rightarrow$ `totals.grand_total`
- **Mapping Invariant**: CORD annotations rarely include tax IDs or purchase orders; missing fields must be mapped to `null` rather than penalized as extraction failures.

### B. Invoices Donut Data (`katanaml-org/invoices-donut-data-v1`)
- **License**: MIT.
- **Format**: A4 structured commercial invoices with JSON ground truth.
- **Field Mapping to Track B**:
  - `invoice_number` $\rightarrow$ `invoice_number`
  - `date` $\rightarrow$ `invoice_date` (normalized via `FieldNormalizer`)
  - `seller` $\rightarrow$ `supplier_name`
  - `table_items` $\rightarrow$ `line_items`
  - `total` $\rightarrow$ `totals.grand_total`
- **Warning on Dataset Merging**: CORD-v2 and Invoices-Donut annotations must **never be merged into a single training/evaluation corpus without format harmonization**. In CORD, `total` often includes tips and service charges, whereas in commercial invoices, `total` includes strict statutory VAT/GST.

---

## 5. Experimental Protocol & Partitioning Strategy

### 5.1 Document-Level Split Independence
- In accordance with ML best practices, all dataset splits (Train 70%, Validation 15%, Test 15%) must be partitioned strictly at the **document and supplier level**.
- Invoices from the same supplier or template must not leak between validation and test splits to prevent overfitting to specific layout typography.
- Prompts, extraction regexes, and validation tolerances must be tuned strictly on the Validation split; the Test split remains sequestered for final reporting.

### 5.2 Evaluated Metrics Hierarchy
Every future model benchmark will output the standardized metrics defined in `MetricCalculator`:
1. **Schema Conformance**: % of candidate outputs that pass `extraction_result_schema.json` without repair.
2. **Arithmetic Consistency**: % of extracted invoices that achieve `RECONCILED` or `RECONCILED_WITH_WARNINGS` via `InvoiceReconciler`.
3. **Line-Item Alignment F1**: Bipartite Hungarian matching between predicted and ground-truth line items (token overlap + price agreement).
4. **Exact Monetary Match vs Tolerance Match**:
   - Exact: $\text{abs}(P - G) == 0.00$
   - Tolerance: $\text{abs}(P - G) \le 0.05$
5. **False Extraction Rate**: Quantifying model hallucinations (extracting values for fields absent from the document).
6. **Inference Latency Profile**: P50, P90, P95, and mean millisecond latency per page.

---

## 6. Execution Guidelines for Future Offline Benchmarking

When hardware assets are provisioned and external model weights staged, execute benchmarks via the isolated environment:

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
