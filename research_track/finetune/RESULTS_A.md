# Track A Results: detector smoke run complete; OCR remains blocked

> Provenance label (applies to any future number): "Indian LPR dataset test split, NOT PEC gate performance".

Status 2026-10-09: **plate-detection smoke training completed; OCR training remains blocked.** The authorized Kaggle payload contains 181 images and YOLO plate boxes but no plate-text labels.

## Plate-detection smoke run

- Dataset: Kaggle `kedarsai/indian-license-plates-with-labels`, CC0-1.0 per Kaggle metadata.
- Split: 145 train / 36 validation images, seed 42; 63 validation plate instances.
- Model: Ultralytics YOLO11n, one `license_plate` class, 3 epochs, RTX 4050, batch 4, image size 640.
- Validation: precision 0.789, recall 0.635, mAP50 0.622, mAP50-95 0.467.
- Peak reported GPU memory: approximately 0.785 GiB.
- Checkpoint: `/home/kirat/ml-assets/campus/runs/track_a/20261009_detector_smoke/plate_detector_smoke/weights/best.pt`.
- Provenance: synthetic/third-party Kaggle benchmark only; not PEC gate performance.

## Extended detector run

- Dataset and split: same 181-image Kaggle payload, 145 train / 36 validation, seed 42.
- Model: YOLO11n, 50 epochs, RTX 4050, batch 4, image size 640.
- Best epoch: 50. Validation precision `0.96273`, recall `0.82018`, mAP50 `0.89699`, mAP50-95 `0.68563`.
- Checkpoint: `/home/kirat/ml-assets/campus/runs/track_a/20261009_detector_full/plate_detector_smoke/weights/best.pt`.
- These are plate-detection metrics only; they do not measure OCR, vehicle classification, association, registry matching, or PEC performance.

## OCR data status

OCR training remains blocked because no authorized Indian plate-text labels are available:

- Indian LPR "in the wild" (arXiv 2111.06054): withheld by the authors ("We can't make dataset public…"); repo has no LICENSE. **MANUAL**: request an academic data-sharing agreement from the authors.
- Kaggle `kedarsai/indian-license-plates-with-labels`: downloaded under `~/ml-assets/campus/datasets/IN-02/`; payload has no OCR text labels.
- IEEE DataPort Indian LPR / IND-VNP: login-gated. **MANUAL**.
- HF Hub search: 10 candidates, all rejected (empty placeholder repos, machine-generated labels, no license, NC-ND sample).

Track A preparation and detector scripts now live under `finetune/track_a/`; OCR scripts remain gated on text-labeled crops.

Readiness facts verified for when data exists (see `PREREQ_REPORT.md` §5):
- Train with `KERAS_BACKEND=torch`. TensorFlow 2.21 in `.venv-ml` cannot load CUDA libraries; torch cu130 sees the GPU.
- The european MobileViT-v2 ONNX is a legacy, inference-only model: use it as the zero-shot baseline only. Fine-tune from `cct_s_v2_global.keras` (fast-plate-ocr release assets, MIT) with an 11-slot `0-9A-Z_` plate config. The head is re-initialized via `--weights-path … skip_mismatch=True`.
- The CLI has no CER metric (use `val_plate_char_acc` for early stopping) and no optimizer-state resume.

## Audit addendum (2026-10-09 09:03): runs found but previously unrecorded

- `runs/track_a/20261009_character_detector`: YOLO11n, 20 epochs on Roboflow `carpallet/license-plate-takqm` v1 (CC BY 4.0). Visual check shows **Iranian plates with Persian digits**, not Indian. Final val P 0.976, R 0.897, mAP50 0.906, mAP50-95 0.690. Out of domain; **not** evidence for Indian plate OCR.
- `runs/track_a/20261009_vehicle_detector`: YOLO11n on Roboflow `vehicle-detection-2g9na` v1 (taxi/truck, CC BY 4.0), 50 epochs (resumed; epochs 26-28 duplicated in results.csv). Final val mAP50 0.963, mAP50-95 0.922. Vehicle detection only; not PEC performance.

## Pretrained plate readers, zero-shot, no training (2026-10-09 09:45)

> Provenance: "IN-02 Kaggle CC0 plate crops, NO text ground truth; proxy signals only, NOT accuracy and NOT PEC gate performance".

Script `scripts/a_pretrained_zeroshot.py` (CPU, 47 s), run dir `~/ml-assets/campus/runs/track_a/20261009_pretrained_zeroshot/` (predictions.csv, summary.json, contact_sheet.jpg, run_manifest.json). 1,840 labelled IN-02 PNG crops.

| Model | License | Indian-format valid | Valid state code | Informal visual check (n=23, by eye, NOT ground truth) |
|---|---|---|---|---|
| Indian_LPR LPRNet (`best_lprnet.pth`) | **none published (all rights reserved)** | 0.922 | 0.899 | 21/23, exact 95% CI [0.72, 0.99] |
| fast-plate-ocr `cct-s-v2-global` | MIT | 0.695 | 0.663 | 12/23, [0.31, 0.73] |
| fast-plate-ocr european MobileViT-v2 | MIT | 0.613 | 0.478 | 0/23, [0.00, 0.15] |

Exact agreement LPRNet vs CCT 0.487. Caveats: (1) LPRNet weights have no license -> local research comparison only; not deployable/redistributable without author permission. (2) The Indian_LPR README recommends this same Kaggle set, so LPRNet may have seen these crops (possible leakage, optimistic). (3) LPRNet has no confidence output and emitted `MH09BB4445` for an illegible crop: any use must stay an observation for human review, never a decision. (4) Two-line plates were the main LPRNet failure. A real accuracy number needs hand-typed labels.
