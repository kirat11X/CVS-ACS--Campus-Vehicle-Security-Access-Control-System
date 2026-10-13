# Research Prototype Review Report

Date: 2026-10-09
Scope: offline static review and CPU-only synthetic verification. No production services, databases, brokers, AWS, GPU, real PII, or PEC frames were used.

## Evidence Summary

| Area | Verified evidence |
|---|---|
| Track A fixtures | 50 registry records, 60 labeled examples |
| Track B fixtures | 32 inputs, 32 independent ground-truth documents, 6 adversarial cases present |
| Track C fixtures | 115 cases, 115 ground-truth records, 320 taxonomy rows, 21 policy rules |
| Staged assets | 22G under the 30G cap; model loading deferred because available RAM was about 3G |
| Review tests | 10 passed under isolated `research_track/review` pytest config |
| Track A synthetic run | 60 cases across baselines 0-3; provisional only until held-out split/oracle artifacts are added |
| Track B synthetic run | 32 documents; schema-valid 100%, arithmetic pass 87.5%, complete exact 87.5%, line-item F1 100% |

All metrics above are synthetic-fixture results only and are not evidence of real-world or PEC performance.

## Findings

| ID | Severity | Track | Location | Evidence | Status |
|---|---|---|---|---|---|
| A-S1-001 | S1 | A | `track_a/src/pipeline.py` | `from_config()` passed unsupported `allow_bh_series`, `enable_confusion_generation`, `max_confusion_variants`, and `confusion_penalty`; documented evaluator failed before processing. | Fixed and regression-tested |
| A-S2-002 | S2 | A | `track_a/config.yaml`, `track_a/src/pipeline.py` | Declared 30/70 split is not materialized by `evaluate_dataset`; the 60-case run evaluates the full corpus. | Open |
| A-S2-003 | S2 | A | `track_a/reports/EVALUATION_PLAN.md` | Published metric table had no result artifact before this review and no held-out evidence. | Open; provisional run now recorded in progress |
| B-S1-001 | S1 | B | `track_b/src/reconciliation.py` | `ValidationFinding.to_dict()` dereferenced `.value` on raw string `VAL_SCHEMA_VIOLATION`. | Fixed and regression-tested |
| B-S1-002 | S1 | B | `track_b/src/extraction_interface.py`, `track_b/schemas/invoice_schema.json` | Validator ignored the declared JSON Schema and accepted unexpected fields/types. | Fixed with strict Draft 2020-12 validation and regression test |
| B-S1-003 | S1 | B | `track_b/src/evaluation.py` | `align_line_items()` originally greedily assigned highest pair scores, contrary to documented optimal bipartite alignment. | Fixed with deterministic maximum-cardinality/maximum-score assignment and corpus regression check |
| B-S2-004 | S2 | B | `track_b/fixtures`, `track_b/src/baseline_extractor.py` | Handling fees, comma-decimal fixture labeling, item-level discount coverage, and multi-page source-page provenance do not fully match documented expectations. | Open |
| C-S1-001 | S1 | C | `track_c/src/policy_engine.py` | Screening event IDs used current wall-clock time, so identical evaluations differed. | Fixed; canonical SHA-256 identity and explicit timestamp required |
| C-S1-002 | S1 | C | `track_c/src/classifier_interface.py`, `track_c/src/policy_engine.py` | Lexical predictions used wall-clock timestamps; uncertain non-UNKNOWN classifications could remain ALLOW. | Fixed and regression-tested |
| C-S1-003 | S1 | C | `track_c/src/policy_engine.py` | Rule-order permutation changed event IDs even when outcomes matched. | Fixed and regression-tested |
| C-S2-004 | S2 | C | `track_c/fixtures/item_taxonomy_seed.csv`, docs | Verified taxonomy count is 320 rows, while reports claim 321 or 300 unique items. | Open; docs need reconciliation |
| X-S1-001 | S1 | Cross-track | Track B/C boundary | No production adapter exists; no executable lossless Decimal/null/unit contract existed before review. | Open |
| X-S2-002 | S2 | Cross-track | `db_draft/`, `frontend/src/` | Draft DB and mocks diverge from nullable confidence, stable reason codes, policy version, and audit fields. | Open; migrations not applied |
| I-S0-001 | S0 | Isolation | workspace Git root | Git root resolves to `/home/kirat`, causing unrelated home-directory paths in status. No cleanup was performed. | Open environmental boundary |
| I-S2-002 | S2 | Isolation | `research_track/frontend/node_modules/` | Existing files exceed 5 MB; no large model/data files were added by this review. | Open; do not delete user files |

## Fine-Tuning Gate

Fine-tuning was not approved and was not run. Track A neural baseline is blocked by absent authorized Indian image annotations and low available RAM. Track B and C model baselines are deferred until CPU resource checks and schema/converter readiness are complete. See `../finetune/FINETUNE_DECISION.md`.
