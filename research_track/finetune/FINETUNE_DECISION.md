# Fine-Tuning Decision

Date: 2026-10-09. G3 status: **APPROVED for A,C on local, $0** (`APPROVE_FINETUNE:A,C:local:0`). Track B was not approved and not touched.
Previous status (same day, before approval): STOPPED, with no token, no training and no GPU.

| Track | Decision | Measured evidence |
|---|---|---|
| A | **DETECTOR TRAINED; OCR BLOCKED** | Kaggle CC0 payload downloaded: 181 images with YOLO plate boxes, no OCR text labels. YOLO11n detector run completed locally on RTX 4050: 145/36 split, 50 epochs, best mAP50 0.89699, mAP50-95 0.68563. Indian_LPR remains withheld; OCR requires authorized text-labeled crops. See `RESULTS_A.md`, `PREREQ_REPORT.md`. |
| B | NOT APPROVED | Unchanged. Deterministic baseline on 32 synthetic invoices (review pass): schema-valid 100%, arithmetic pass 87.5%. Consented screenshots and EC2 are required. |
| C | **TRAINED (synthetic only); GO for research comparison, NO-GO for any domain or production claim** | QLoRA Qwen3-1.7B, test n=63 evaluated once: accuracy **0.841 [0.746, 0.921]**, macro-F1 **0.818 [0.656, 0.904]**, against lexical 0.365 [0.238, 0.476] / 0.445 and zero-shot 0.333 / 0.432. Paired 95% CI of the gain over lexical: acc +0.33 to +0.62. 0% invalid outputs; 1 of 4 gold-UNKNOWN items labelled NORMAL. 251 s, 3.77 GiB peak. **Label: synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy.** See `RESULTS_C.md`. |

## Still required before any target-domain claim

- Track A: authorized Indian plate images with text labels (Kaggle token or an author agreement), then PEC gate frames for a separate, consented evaluation.
- Track C: a human-labelled, family-grouped held-out set of real (consented) line items, including UNKNOWN and ambiguous cases; a calibrated confidence signal before the policy engine consumes model NORMAL labels.
- Track B: separate approval token, consented invoice screenshots, EC2 host/key.

No number in this document is a claim of real-world or PEC performance.
