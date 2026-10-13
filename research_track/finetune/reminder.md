# Reminder: Track A / Track C follow-ups (written 2026-10-09)

## To do (you)

- [ ] **Hand-label ~200 IN-02 plate crops** for a real accuracy number. Write `image_path,plate_text` CSV (no spaces, e.g. `MH12AB1234`; two-line plates top row first) for crops in `~/ml-assets/campus/datasets/IN-02/extracted/images/License (*).png`. Do not use OCR output as labels.
- [ ] **Get licensed Indian plate-text data** to unblock OCR fine-tuning (any one):
  - Email the Indian_LPR authors (arXiv 2111.06054) for a data-sharing agreement, and ask permission to use `best_lprnet.pth` beyond local research.
  - IEEE DataPort (login required, check license): "VisionPlate ANPR" and "Indian License Plate Recognition Dataset (YOLO & OCR)". Save under `~/ml-assets/campus/datasets/`.
- [ ] **Before any more GPU training, stop the backend (uvicorn :8000) and Frigate yourself.** MemAvailable was 7.57 GiB (< 8 GB gate).
- [ ] Track B: needs its own approval token, consented invoice screenshots, and EC2 host/key.
- [ ] PEC gate frames (consented) for a separate Track A evaluation; real human-labelled line items for Track C.

## Remember

- Best pretrained plate reader now: **Indian LPRNet** (21/23 by eye, CI 0.72-0.99), but **no license** -> thesis comparison only, possible leakage with IN-02, no confidence, hallucinates on unreadable crops. Deployable/fine-tunable alternative: fast-plate-ocr `cct-s-v2-global` (MIT, 12/23).
- Readers output **observations for human review, never decisions**.
- `runs/track_a/20261009_character_detector` was trained on **Iranian** plates (carpallet): do not cite as Indian performance.
- Track C test split was already used once (`runs/C/eval/TEST_EVALUATED.lock`): do not retrain and re-test on the same split.
- Never run `git add -A` from `~` (git root is `/home/kirat`, includes `~/ml-assets`). Scope git with `-- research_track`.

Details: `PREREQ_REPORT.md` (Re-audit), `RESULTS_A.md`, `RESULTS_C.md`, `PROGRESS_TRAIN.md`.
