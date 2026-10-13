# Model card: `track-c-qwen3-1.7b-qlora-full_c_v1` (LoRA adapter)

- **Artifact:** `~/ml-assets/campus/runs/C/full_c_v1/adapter/` (PEFT LoRA, `adapter_model.safetensors`); a copy of this card sits next to it as `MODEL_CARD.md`.
- **Base model:** Qwen/Qwen3-1.7B (local `~/ml-assets/campus/models/Qwen3-1.7B`), loaded 4-bit NF4. **License:** Apache-2.0, inherited by the adapter. Keep the base LICENSE and NOTICE when redistributing.
- **Task:** map one invoice line-item string to exactly one of 8 codes: TOBACCO_NICOTINE, ALCOHOL, RX_SCHEDULED_DRUG, OTC_MEDICINE, HAZARDOUS_CHEMICAL, SHARP_OBJECT, NORMAL, UNKNOWN. The prompt lives in `finetune/scripts/c_common.py` (`SYSTEM_PROMPT`, thinking disabled). Decode greedily; anything not exactly a code → UNKNOWN (never NORMAL).
- **Data provenance:** 188 synthetic, LLM-authored training items from `track_c/fixtures/item_taxonomy_seed.csv` (project-internal synthetic; no real PII, no real invoices). Family-grouped split `split_v1`.
- **Training:** QLoRA r=16, alpha=32, lr 2e-4 (validation probe), best epoch 3 of 5, 251 s on an RTX 4050 Laptop, peak 3.77 GiB reserved. Hyperparameters are unverified starting points.
- **Evaluation:** test (n=63, evaluated once): accuracy 0.841 [0.746, 0.921], macro-F1 0.818 [0.656, 0.904]. Lexical baseline: 0.365 / 0.445. **Label: synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy.** Full details in `finetune/RESULTS_C.md`.
- **Intended use:** research comparison of classifiers inside the isolated `research_track`. It is an *observation* that proposes a category. The deterministic policy engine decides ALLOW/REVIEW/ALERT, with a human in the loop.
- **Out of scope:** any direct screening decision, barrier/gate control, production wiring, or claims about real campus invoices.
- **Known limitations and risks:** labelled 1 of 4 test UNKNOWN items as NORMAL; over-escalates dosage-bearing OTC/nicotine items to RX; weak on Hinglish and truncated SKUs; no calibrated confidence (emit `confidence=None` → REVIEW under the current policy config); tiny synthetic test set.
