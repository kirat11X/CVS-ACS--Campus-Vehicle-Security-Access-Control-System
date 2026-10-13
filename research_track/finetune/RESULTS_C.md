# Track C Results: Qwen3-1.7B QLoRA item-category classifier

> **Provenance label:** synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy.
> **Scope:** classifier metrics only. No ALLOW/REVIEW/ALERT outcome was computed or is reported. The model proposes a category; the deterministic policy engine stays authoritative.

Date 2026-10-09. Approval `APPROVE_FINETUNE:A,C:local:0`, local RTX 4050 6 GB, $0. The user chose to continue with Track C only after the Track A data gate stopped Track A.

## Data and split

- Source: `track_c/fixtures/item_taxonomy_seed.csv`. 320 rows = the 300-row synthetic seed (sha256 `150a1bef…`, identical rows) + 20 UNKNOWN rows. 8 codes.
- Split `runs/C/split_v1` (`c_split.py`, seed 42): **grouped by brand/template family**. Families are linked with union-find over rare shared tokens, a consonant skeleton of the brand token (truncations such as "Srf Excl" / "Surf Excel"), and near-duplicate similarity. This gives 191 families. StratifiedGroupKFold fold 0 = test and fold 1 = val. Asserted: no family and no normalized text spans two splits. Grouping errs toward over-merging, e.g. the token "Wht" links a wine with a bread.
- Sizes: train 188 / val 69 / test 63. Test support per class: TOB 5, ALC 6, RX 5, OTC 6, HAZ 5, SHARP 4, NORMAL 28, UNKNOWN 4.

## Training (`full_c_v1`)

| Item | Value |
|---|---|
| Base | Qwen3-1.7B (Apache-2.0), NF4 4-bit + double quant, bf16 compute, thinking disabled in the chat template |
| Adapter | LoRA r=16, alpha=32, dropout 0.05, q/k/v/o/gate/up/down; loss on completion tokens only; max length 256; gradient checkpointing |
| Optimizer | lr 2e-4 cosine, warmup 5%, batch 8, up to 8 epochs, early stopping on val loss (patience 2) |
| Hyperparameter status | **Unverified starting points.** LR was picked by a 3-epoch validation-only probe: 2e-4 → val acc .783 / mF1 .673; 1e-4 → .739 / .658; 5e-5 → .754 / .669 (n=69; differences are within noise). |
| Outcome | COMPLETED; early stop after epoch 5; best = epoch 3 (`checkpoint-72`, val loss 0.2218) |
| Wall time | 251 s (cap 60 min). All GPU work in this pass, including smoke, probe, full run and evals: ≈ 15 min. |
| Peak VRAM | 3.49 GiB allocated / 3.77 GiB reserved (torch); 4.0 GB total on the GPU (watchdog); max GPU temp 79 °C; no watchdog trips |

## Test split (evaluated once: `eval/test_full_c_v1`, lock file present, re-run refused)

n = 63. 95% CIs use a percentile bootstrap (2,000 item-level resamples, paired across models).

| Model | Accuracy [95% CI] | Macro-F1 [95% CI] | UNKNOWN rate | Invalid output | gold UNKNOWN → NORMAL |
|---|---|---|---|---|---|
| Lexical baseline (train-split keyword map + built-in heuristics) | 0.365 [0.238, 0.476] | 0.445 [0.284, 0.549] | 69.8% | n/a | 0 |
| MiniLM kNN (k=5, τ=0 tuned on val) | 0.540 [0.413, 0.667] | 0.406 [0.280, 0.501] | 1.6% | n/a | **3** |
| Qwen3-1.7B zero-shot | 0.333 [0.222, 0.444] | 0.432 [0.290, 0.522] | 65.1% | 14.3% | 0 |
| **Qwen3-1.7B + QLoRA** | **0.841 [0.746, 0.921]** | **0.818 [0.656, 0.904]** | 4.8% | 0.0% | **1** |

Paired bootstrap deltas (test):
- QLoRA − lexical: accuracy +0.333 to +0.619, macro-F1 +0.209 to +0.546 (95% CI; 0/2000 resamples ≤ 0).
- QLoRA − zero-shot: accuracy +0.365 to +0.635, macro-F1 +0.223 to +0.539 (0/2000 ≤ 0).

On the validation split (the model was selected there, so these numbers are optimistic): QLoRA 0.754 [0.652, 0.855] acc / 0.666 [0.504, 0.781] mF1; lexical 0.449 / 0.547; kNN 0.449 / 0.346; zero-shot 0.232 / 0.315. Test scoring above val fits small-n noise (63 and 69 items, wide CIs) plus family-grouped splits that differ in difficulty. It is not evidence of generalization.

The lexical baseline's keyword map is built from the **train split only**. The shipped `LexicalMappingClassifier.from_csv` loads every taxonomy row, which would include the test items; that leakage is avoided here.

### QLoRA per-class (test)

| Class | P | R | F1 | n |
|---|---|---|---|---|
| TOBACCO_NICOTINE | 1.00 | 0.60 | 0.75 | 5 |
| ALCOHOL | 0.86 | 1.00 | 0.92 | 6 |
| RX_SCHEDULED_DRUG | 0.56 | 1.00 | 0.71 | 5 |
| OTC_MEDICINE | 0.50 | 0.50 | 0.50 | 6 |
| HAZARDOUS_CHEMICAL | 1.00 | 0.80 | 0.89 | 5 |
| SHARP_OBJECT | 1.00 | 1.00 | 1.00 | 4 |
| NORMAL | 0.93 | 0.89 | 0.91 | 28 |
| UNKNOWN | 1.00 | 0.75 | 0.86 | 4 |

Confusion matrix (rows = gold, cols = pred, order as above): `[[3,0,2,0,0,0,0,0],[0,6,0,0,0,0,0,0],[0,0,5,0,0,0,0,0],[0,0,2,3,0,0,1,0],[0,0,0,1,4,0,0,0],[0,0,0,0,0,4,0,0],[0,1,0,2,0,0,25,0],[0,0,0,0,0,0,1,3]]`

## Error analysis (all 10 QLoRA test errors)

| Item | Gold → Pred | Style |
|---|---|---|
| Badi Advance sutta | TOBACCO → RX | hinglish |
| Nicotine patch 21mg | TOBACCO → RX | normal_grocery |
| Crocin Advance 500mg | OTC → RX | normal_grocery |
| gale ki khich khich goli | OTC → RX | hinglish |
| Eno Lemon Sachet | OTC → NORMAL | normal_grocery |
| macchar maar spray | HAZ → OTC | hinglish |
| Amul Tz 500ml | NORMAL → ALCOHOL | quick_commerce_truncated |
| Sensodyne Repair 70g | NORMAL → OTC | normal_grocery |
| Vim Gel 500m | NORMAL → OTC | quick_commerce_truncated |
| **koi anjaan samaan** ("some unknown item") | **UNKNOWN → NORMAL** | hinglish |

Patterns:
1. Dosage strings ("500mg", "21mg", "goli" = pill) pull items toward RX. 4 of 10 errors are over-escalations. This is the conservative direction, but it inflates review load.
2. Hinglish phrasing accounts for 4 of 10 errors.
3. Truncated SKUs ("Amul Tz", "Vim Gel 500m") are under-specified.
4. **Safety-relevant:** one truly unidentifiable item was labelled NORMAL. Output parsing never maps to NORMAL (invalid → UNKNOWN; 0 invalid outputs on test), but the model's own label can still be NORMAL for an UNKNOWN item. MiniLM kNN did this 3 times. **Before any integration, the policy layer must not treat a model NORMAL as sufficient for ALLOW without a confidence signal.** This adapter currently emits no calibrated confidence: generation-only, so `confidence=None`, which the existing policy config treats as REVIEW (`treat_missing_confidence_as_review: true`).

## Limitations

- All items are synthetic and LLM-authored. The test set has only 63 items (4–6 per minority class), so the CIs are wide and per-class numbers are anecdotal.
- No real invoices, no OCR noise from Track B, no consented screenshots, no human-labelled held-out set.
- One seed and one split. Re-evaluating val with a freshly loaded adapter gave 0.754 vs 0.768 at train time (1 item of 69), a small numeric non-determinism from 4-bit kernels and batching.
- `scripts_sha256` in the manifests was recorded at run time. `c_common.git_sha()` was edited afterwards to fix a manifest-only bug (it recorded "HEAD" for a commit-less repo). Training and eval code are unaffected.

## Artifacts

- Adapter: `~/ml-assets/campus/runs/C/full_c_v1/adapter/` (model card `MODEL_CARD.md`); manifest, `log_history.json`, `train.log`, `watchdog.log` in the same run dir.
- Evals: `~/ml-assets/campus/runs/C/eval/{val_full_c_v1,test_full_c_v1}/` (`eval_report.json`, `predictions.json`, `run_manifest.json`); `TEST_EVALUATED.lock`.
- Small results JSON: `track_c/results/qlora_full_c_v1_metrics.json`.
- Scripts: `finetune/scripts/{c_common,c_split,c_infer,c_train_lora,c_eval}.py`, `run_track_c.sh`.
- No production wiring: the Phase 5A resolver, backend, Frigate and db_draft were not touched.
