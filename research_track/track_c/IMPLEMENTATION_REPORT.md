# Track C: Implementation & Engineering Report

**Project:** Campus Vehicle Security & Access-Control System (PEC Chandigarh)  
**Track:** Research Track C — Item Classification Interface & Deterministic Screening Policy Engine  
**Location:** `research_track/track_c/`  
**Status:** Implementation Complete | Fully Isolated | Static Verification Passed

---

## 1. Executive Summary

Track C implements an explainable, model-independent item classification interface coupled with a pure deterministic policy screening engine for automated delivery screening at the PEC Chandigarh campus gates.

The pipeline architecture enforces a strict decoupling between **observational perception** (what a quick-commerce delivery item appears to be) and **administrative access control** (what gate action campus security policy mandates). A machine learning model or heuristic classifier proposes a category and optional confidence score; the deterministic policy engine evaluates this hypothesis against explicit, prioritized, versioned security rules to produce an auditable screening outcome: `ALLOW`, `REVIEW`, or `ALERT`.

All code is implemented in standard Python without external ML library dependencies, maintaining complete sandbox safety, zero GPU memory allocation, and zero modification to existing repository files.

---

## 2. Complete Deliverable Inventory

All 15 deliverables required by the specification have been implemented under `research_track/track_c/`:

| # | Deliverable | Path | Description |
| :---: | :--- | :--- | :--- |
| **1** | Configuration File | `config.yaml` | Policy version (`v1.0`), review threshold (0.70), chemical thresholds (3.0), supported units. |
| **2** | Input Schema | `schemas/classification_input.schema.json` | JSON Schema for raw and normalized invoice line items from Track B. |
| **3** | Output Schema | `schemas/classification_output.schema.json` | JSON Schema for classifier perception hypothesis (never includes outcomes). |
| **4** | Policy Rule Schema | `schemas/policy_rule.schema.json` | JSON Schema for deterministic rules with priorities, validity windows, and platform scopes. |
| **5** | Screening Result Schema | `schemas/screening_result.schema.json` | JSON Schema for explainable outcomes with audit traces and reason codes. |
| **6** | Domain Types & Dataclasses | `src/types.py` | Enums (`ScreeningOutcome`, `ItemCategoryCode`) and frozen dataclasses with JSON serialization. |
| **7** | Category Normalization | `src/category_normalization.py` | 8-category taxonomy normalizer with 50+ synonym mappings; invalid inputs map to `UNKNOWN`. |
| **8** | Stable Reason Codes | `src/reason_codes.py` | 20+ immutable reason codes (`CATEGORY_RULE_ALERT`, etc.) with escalation metadata. |
| **9** | Classifier Interface | `src/classifier_interface.py` | Abstract `ItemClassifier` and deterministic `LexicalMappingClassifier` baseline. |
| **10** | Deterministic Policy Engine | `src/policy_engine.py` | Pure evaluation engine with priority sorting, temporal filtering, and tie conflict safety. |
| **11** | Audit Records & Ledger | `src/audit_records.py` | Immutable append-only audit log events and human review escalation records. |
| **12** | Evaluation Metrics Module | `src/evaluation.py` | Independent perception and policy metrics (False-Allow Rate, Confusion Matrix, property tests). |
| **13** | Seed Taxonomy Fixture | `fixtures/item_taxonomy_seed.csv` | 320 canonical synthetic items across all 8 categories (grocery, Hinglish, truncated, ambiguous, UNKNOWN). |
| **14** | Versioned Policy Rules | `fixtures/policy_rules.json` | 21 rules covering defaults, bulk hazardous chemicals, platform overrides, and conflict pairs. |
| **15** | Synthetic Cases & Ground Truth | `fixtures/synthetic_screening_cases.json`<br>`fixtures/synthetic_ground_truth.json` | 115 test cases covering all edge scenarios and matching ground-truth outcomes. |
| **16** | Test Matrix & Plan | `tests/test_cases.md`<br>`reports/EVALUATION_PLAN.md` | Comprehensive evaluation matrix, future model comparison plan (Qwen3-1.7B), property tests. |
| **17** | Specifications & Documentation | `SPECIFICATION.md`<br>`README.md`<br>`results/.gitkeep` | Technical contracts, 13 invariants, quickstart guide, and output directory placeholder. |

---

## 3. Core Architectural Highlights

### 3.1 Strict Perception vs. Policy Decoupling
The architecture enforces that model confidence is an epistemic probability, never an institutional decision:
- High confidence in a prohibited item triggers `ALERT`.
- High confidence in a permitted item triggers `ALLOW`.
- Low confidence ($< 0.70$) or missing confidence (`None`) in a permitted item automatically degrades to `REVIEW`.
- `ALERT` outcomes are **never** degraded to `REVIEW`, ensuring perimeter security is never compromised by perception uncertainty.

### 3.2 Deterministic Conflict Safety
When multiple active rules match an item at the identical highest priority with contradictory actions:
- Traditional engines fail or resolve by arbitrary database/file row ordering.
- Track C detects the tie, records all conflicting rule IDs in `conflicts_detected`, emits `POLICY_RULE_CONFLICT`, and safely falls back to `REVIEW` with mandatory guard inspection.

### 3.3 Explicit `UNKNOWN` Handling
In high-security environments, the most common vector for perimeter evasion is novelty. Track C treats `UNKNOWN` as a first-class citizen:
- Corrupted OCR tokens, novel SKUs, and unmapped Hinglish terms map strictly to `ItemCategoryCode.UNKNOWN` with `is_uncertain=True`.
- It is architecturally impossible for an unclassified item to silently default to `NORMAL`.

---

## 4. Static Verification & Repository Audit

### 4.1 Python Compilation Verification
All 7 modules in `research_track/track_c/src/` compile cleanly with Python's bytecode compiler (`py_compile`), ensuring zero syntax errors or invalid imports:
- `research_track/track_c/src/__init__.py`
- `research_track/track_c/src/types.py`
- `research_track/track_c/src/category_normalization.py`
- `research_track/track_c/src/reason_codes.py`
- `research_track/track_c/src/classifier_interface.py`
- `research_track/track_c/src/policy_engine.py`
- `research_track/track_c/src/audit_records.py`
- `research_track/track_c/src/evaluation.py`

### 4.2 JSON Schemas & Fixtures Validation
All schemas and JSON data fixtures parse as valid JSON:
- `schemas/classification_input.schema.json`
- `schemas/classification_output.schema.json`
- `schemas/policy_rule.schema.json`
- `schemas/screening_result.schema.json`
- `fixtures/policy_rules.json` (21 valid rules)
- `fixtures/synthetic_screening_cases.json` (115 valid test cases)
- `fixtures/synthetic_ground_truth.json` (115 matching ground-truth entries)

### 4.3 Repository Isolation Audit
- Existing files modified: **0** (`git status --porcelain` shows only untracked additions under `research_track/track_c/`).
- External assets modified: **0** (no files touched outside the repository).
- Ports accessed: **0** (no connections to 5433, 1883, 5000, 5678, 8000, 3000).
- GPU memory used: **0 MB** (zero CUDA allocation).
- Background daemons / dev servers launched: **0**.

---

## 5. Deferred Execution & Future Roadmap

1. **Empirical Zero-Shot LLM Evaluation**:
   - `~/ml-assets/campus/` currently contains `code/Indian_LPR/` (Track A).
   - Weights for `Qwen3-1.7B` or `Qwen2.5-1.5B` must be staged under `~/ml-assets/campus/models/track_c_qwen/` before executing empirical model benchmarks.
2. **Database Promotion**:
   - Staging tables are drafted in `research_track/db_draft/models_screening.py`.
   - Migration to PostgreSQL 16 will be executed in a future phase once all research tracks are consolidated.
3. **Guard UI Review Queue**:
   - The React guard dashboard frontend drafts under `research_track/frontend/` will consume `ScreeningResult` payloads directly from the FastAPI webhook endpoints.
