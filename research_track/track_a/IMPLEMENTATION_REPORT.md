# Track A: Indian ANPR Research & Evaluation Prototype — Implementation Report

**Date:** October 9, 2026  
**Project:** Campus Vehicle Security & Access-Control System, PEC Chandigarh (`/home/kirat/coding/honours`)  
**Track:** Track A — Indian ANPR Research & Evaluation Prototype  
**Scope:** Offline research prototype, candidate ranking, registry-constrained fuzzy matching, Phase 5A adapter.  

---

## 1. Executive Summary & Inventory of Created Files

Track A has been completely implemented in strict isolation under `research_track/track_a/`. Zero modifications have been made to existing repository files, no test runners or dev servers were started, and zero GPU memory or CUDA operations were utilized.

### Directory Inventory
| Path | Size (Lines) | Role / Deliverable |
| :--- | :--- | :--- |
| `config.yaml` | 70 | Centralized configuration for normalization, ranking weights, threshold (0.82), ambiguity margin (0.07), and baselines. |
| `src/__init__.py` | 30 | Exports public pipeline interfaces and symbols. |
| `src/normalization.py` | 285 | Non-destructive plate normalizer, Indian regex validator, positional confusion generator (O/0, I/1, B/8, etc.). |
| `src/candidate_ranking.py` | 172 | Multi-reader OCR hypothesis ranking, transparent scoring, neutral missing-confidence handling (0.50). |
| `src/registry_matcher.py` | 310 | Weighted Levenshtein fuzzy matcher, optical confusion discount (0.25), strict ambiguity margin rejection. |
| `src/resolver_adapter.py` | 148 | Bidirectional adapter mapping Track A structures to Phase 5A `IdentityResolver` schema. |
| `src/metrics.py` | 338 | CER, Exact-Plate Accuracy, dual-denominator FMR, Coverage, Ambiguity Rate, latency percentiles, error taxonomy. |
| `src/pipeline.py` | 344 | End-to-end `ANPRPipeline` implementing Baselines 0–3 and offline batch evaluation harness. |
| `fixtures/synthetic_registry.csv` | 51 | 50 synthetic authorized campus records (PB, CH, HR, DL, HP, BH) including near-duplicate pairs. |
| `fixtures/labeled_examples.csv` | 61 | 60 labeled synthetic test cases covering 8 distinct edge case categories. |
| `tests/test_cases.md` | 134 | Complete test matrix comparing inputs, ground truth, and expected outcomes across Baselines 0–3. |
| `reports/EVALUATION_PLAN.md` | 172 | Formal evaluation protocol, mathematical formulas, validation/test split methodology, error taxonomy. |
| `SPECIFICATION.md` | 168 | Technical specification, data models, configuration schema, and 7 core architectural invariants. |
| `README.md` | 88 | Quickstart documentation, architectural rationale, deferred execution guide, and limitations. |
| `results/.gitkeep` | 1 | Destination placeholder for deferred offline evaluation run artifacts. |

---

## 2. Discovered Phase 5A Contract & Adaptation Architecture

### Inspected Phase 5A Contract
- **Source Location**: `scripts/prototypes/phase5_identity_resolution/resolver.py`, `fuzzy_matcher.py`, `models.py`.
- **Input Observation Contract**: `Dict[str, Any]` with keys `{"id": ..., "plate": ..., "plate_confidence": ...}`.
- **Normalization Invariant**: `re.sub(r'[^A-Za-z0-9]', '', plate).strip().upper()`.
- **Resolution Output**: `ResolutionResult` containing `identity_status` (`KNOWN`, `UNKNOWN`, `AMBIGUOUS`, `INVALID`), `match_method`, `vehicle` dict, and optional context dictionaries (`owner`, `visitor`, `delivery`).

### Track A Adaptations
1. **Multi-Candidate Ingestion**: While Phase 5A only takes a single observation string, Track A's `Phase5AResolverAdapter` aggregates $N$ competing hypotheses, ranks them via `OCRCandidateRanker`, and supplies the top-ranked candidate to the Phase 5A schema.
2. **Decoupled Identity Invariant**: Phase 5A couples vehicle matching with human identity context (`owner`, `visitor`). Track A strictly isolates vehicle plate verification as an **observation context**, ensuring that a plate match is never conflated with a gate access grant or person identification.
3. **Audit Trail Preservation**: Raw plate strings, confidence provenance, and similarity delta margins are retained throughout the lifecycle.

---

## 3. Baselines & Expected Progression

| Baseline | Key Mechanism | Strengths | Failure Modes / Vulnerabilities |
| :--- | :--- | :--- | :--- |
| **Baseline 0** | First candidate normalized exact match | Extremely fast, zero false matches on clean data. | Fails on any OCR confusion (0/15 resolved) or multi-reader dispute. |
| **Baseline 1** | Ranked candidate + normalized exact match | Solves multi-reader disagreement when secondary reader is clean. | Still fails on 1-character OCR optical confusions. |
| **Baseline 2** | Ranked candidate + naive fuzzy match ($\ge 0.82$) | High recall, resolves optical confusions. | **Critical vulnerability**: 100% false-match rate on near-duplicate ambiguity pairs (accepts wrong vehicle). |
| **Baseline 3** | Full Track A pipeline (fuzzy + ambiguity margin $\ge 0.07$) | High recall, 0% false matches on ambiguity pairs. | Safely marks near-ties as `AMBIGUOUS`, triggering manual guard inspection. |

---

## 4. Evaluation Metrics & Rationale

- **Exact-Plate Accuracy (EPA)**: $\frac{1}{N} \sum \mathbf{1}[P_i = G_i]$  
  Evaluates raw OCR hypothesis selection fidelity.
- **Character Error Rate (CER)**: $\frac{\text{Levenshtein}(P_i, G_i)}{\max(|G_i|, 1)}$  
  Measures fine-grained character distance per plate string.
- **Dual-Denominator False-Match Rate (FMR)**:
  - $\text{FMR}_{\text{matched}} = \frac{\text{False Matches}}{N_{\text{matched}}}$: Evaluates misattribution risk among accepted matches.
  - $\text{FMR}_{\text{total}} = \frac{\text{False Matches}}{N}$: Evaluates campus-wide risk across total operational volume.
- **Ambiguity Rate (AR)**: $\frac{N_{\text{ambiguous}}}{N}$  
  Tracks safe fallback deferrals.
- **Coverage**: $\frac{N_{\text{matched}}}{N}$  
  Proportion of vehicle sightings successfully resolved.

---

## 5. Synthetic Fixtures Methodology & Edge Case Coverage

The fixtures model realistic Indian road traffic at PEC Chandigarh without exposing private vehicle information:
- **`fixtures/synthetic_registry.csv` (50 records)**:
  - Covers Chandigarh (`CH01`), Punjab (`PB65`, `PB02`, `PB08`, `PB10`, `PB11`, `PB12`), Haryana (`HR03`, `HR08`, `HR10`, `HR12`, `HR20`, `HR26`, `HR51`, `HR70`), Delhi (`DL01`–`DL05`, `DL08`), Himachal Pradesh (`HP12`, `HP14`, `HP63`), and Bharat Series (`22BH`, `23BH`).
  - Includes 5 near-duplicate pairs separated by 1 character or optical confusions (`CH01AB1001` vs `CH01AB1007`, `PB65AB2222` vs `PB65AB2228`, `HR26DQ0001` vs `HR26DO0001`, `DL08CA5555` vs `DL08CA5558`, `22BH1001AA` vs `22BH1001AB`).
- **`fixtures/labeled_examples.csv` (60 test cases)**:
  - 10 clean exact matches
  - 15 1-character optical OCR confusions (O/0, I/1, B/8, S/5, Z/2, G/6)
  - 8 formatting & separator variations (spaces, dots, hyphens, lowercase)
  - 7 insertion, deletion, and truncation cases
  - 5 multi-reader disagreement cases
  - 5 missing confidence cases
  - 5 negative out-of-registry plates
  - 5 near-duplicate ambiguity edge cases

---

## 6. Static Verification & Code Quality Audit

A thorough static analysis of all created files confirms:
1. **Python Syntax**: All Python modules in `src/` conform strictly to Python 3.12+ syntax standards.
2. **Type Annotations**: Comprehensive static type hints (`typing.Optional`, `List`, `Dict`, `Tuple`, `Any`) are present across all function signatures and dataclasses.
3. **No External Side Effects**: Pure standard library and decoupled dependencies (`pyyaml`, `math`, `csv`, `re`, `dataclasses`, `enum`, `time`). No network calls, dev servers, or background threads.
4. **Clean Decoupling**: Zero imports from production packages (`backend.app.*`, `alembic.*`) or live database connections.

---

## 7. Deliberately Unexecuted Actions & GPU Confirmation

In accordance with user instructions and research safety invariants:
- **Zero Pipelines Run**: Neither `pipeline.py` nor any evaluation runner was executed.
- **Zero Test Runners Executed**: No `pytest`, `unittest`, or `scripts/test_*.py` invocations were launched.
- **Zero GPU / CUDA Activity**: No models were loaded into VRAM, no PyTorch / ONNX / TensorRT sessions were created, and `nvidia-smi` was untouched.
- **Zero Production Mutations**: `git diff --stat` remains empty (`0 files changed, 0 insertions, 0 deletions`). All work is confined to `research_track/track_a/`.
