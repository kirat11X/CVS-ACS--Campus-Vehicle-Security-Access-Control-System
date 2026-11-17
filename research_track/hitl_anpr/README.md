# HITL ANPR: human-in-the-loop self-training for Indian number plates

Research track of the PEC campus vehicle-security project. A YOLO plate detector and an OCR engine **propose**
plate boxes and reads; people approve or correct them; only approved data trains the next model; a model replaces
the champion only if it is better on a frozen GOLD set. The campus backend's deterministic rules decide what an
observation means. **Nothing here controls a barrier.**

```
ingest -> predict -> select -> review -> assemble -> train -> evaluate -> promote -> (next round)
 video     boxes,    audit 10%  people /   reviewed    from      GOLD only  gate +     stop when GOLD gain
 frames    tracks,   + uncert-  oracle     + >=30%     champion            registry  < 0.5 pt for 2 rounds
 (2 fps)   OCR       ainty      (audit     replay                                    or budget spent
                                 log)
```

## Guardrails (enforced in code, covered by tests)

| rule | where |
|---|---|
| Split by video / site **before** any frame is used; splits are frozen | `splits.VideoRegistry`, `ingest.py` |
| Near-duplicate leakage check (dHash) across splits, and train/val vs GOLD before every round | `splits.leakage_check`, `dataset.assemble` |
| Never train on unreviewed model output: only `accept`/`correct` decisions on frames whose reviewer confirmed *every plate is boxed* | `review/service.py` (`trainable`) |
| Hash-chained, append-only audit log of every decision (reviewer, time, frame hash, proposal, approval) | `chainlog.py`, `review/service.py` |
| Auto-accept off; it could only open when the Wilson 95% lower bound of audit precision >= 0.98 (needs >= 189 perfect random audits) | `review/service.py` |
| GOLD frozen: every image, label and crop re-hashed before every evaluation | `evaluate.verify_gold` |
| Promotion: >= +1 pt mAP50-95 or >= +2 pt exact match, no slice (n >= 30) down > 2 pt, same GOLD | `promote.py` |
| Registry with version, weights hash, data-manifest hash, config hash, git SHA, metrics; one-command rollback | `registry.py` |
| `fliplr` must be 0 (a mirrored plate is not a plate); one class `license_plate` | `config.py` |
| Plate text never printed by the CLI; payloads to the backend are proposals (dry run by default) | `cli.py`, `propose.py` |
| Ultralytics usage events off per process; OpenVINO telemetry declined in an isolated HOME during export | `yolo.py`, `export.py` |

## Layout

```
research_track/hitl_anpr/
├── config.yaml                 every tunable; its SHA-256 goes into the registry and model card
├── requirements.lock           exact environment (torch from the cu130 index)
├── Makefile                    test / lock / round / review / export / AWS targets
├── MODEL_CARD_TEMPLATE.md      filled by `anpr model-card`
├── src/anpr_hitl/
│   ├── cli.py                  `anpr` command (one subcommand per stage, plus run-round)
│   ├── config.py store.py hashing.py manifest.py chainlog.py labels.py plates.py splits.py
│   ├── indian_plates.py        every Indian plate format + exceptions (Delhi, Karnataka, BH, military ...); see INDIAN_PLATE_FORMATS.md
│   ├── ingest.py               fixed-rate sampling, blur / near-duplicate drop, EXIF-free JPEGs
│   ├── bootstrap.py            seed / pool / val + provisional GOLD + OCR dev set from public data
│   ├── train.py                resume-safe training (verified checkpoint per epoch, STOP file, heat guard)
│   ├── ocr.py                  RapidOCR / Tesseract / fast-plate-ocr behind one interface, per-char confidence
│   ├── predict.py              detector + ByteTrack (10 fps) + OCR on each track's best crops
│   ├── selection.py            random audit + uncertainty / rare-slice ranking + diversity + budget
│   ├── review/service.py       decisions, audit log, training gate, auto-accept gate
│   ├── review/app.py           Streamlit review app (127.0.0.1 only)
│   ├── oracle.py               simulated reviewer for the public pool (demo)
│   ├── dataset.py              round training set: reviewed frames + replay, GOLD exclusion
│   ├── evaluate.py             GOLD metrics, slices, bootstrap CIs, OCR benchmark
│   ├── promote.py registry.py  promotion gate, model registry, rollback
│   ├── rounds.py               resumable round orchestration, stopping rule
│   ├── export.py               ONNX + OpenVINO, parity, Frigate decoding check
│   ├── propose.py              backend observation payloads (proposals only)
│   ├── modelcard.py yolo.py cloud.py
├── aws/                        Dockerfile, CloudFormation, launch / spot / idle scripts
└── tests/                      pytest (fast suite + one GPU resume test)
```

Private data never enters git. Everything lives under `data_root` (default `~/ml-assets/campus/hitl`):
`frames/`, `bootstrap/`, `gold/`, `rounds/<id>/` (predictions, crops, queue), `reviews/audit_log.jsonl`,
`datasets/`, `runs/`, `registry/`, `evals/`, `exports/`.

## Setup

```bash
cd research_track/hitl_anpr
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python --extra-index-url https://download.pytorch.org/whl/cu130 -r requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
make test                                   # fast suite (no GPU)
```

## Commands, stage by stage

```bash
A=.venv/bin/anpr
# 0. data (once): public licence-cleared sets -> seed / pool / val, provisional GOLD, OCR dev set
$A bootstrap-data
$A ingest ../../input/ --source "Pexels (user-supplied)" --licence "Pexels licence"   # split per video, frozen
# 1. bootstrap champion (resumes if interrupted; `touch runs/r00_bootstrap/STOP` stops cleanly)
$A train-bootstrap --run r00_bootstrap
$A register-bootstrap --run r00_bootstrap   # GOLD evaluation, registry v0001, promoted
# 2. one round, end to end (stops at the review step until the queue is done)
$A run-round --round r01 --source public --oracle          # simulated reviewer on the public pool
$A run-round --round r02 --source video --videos ../../input/   # people review in the app:
$A review-app --round r02                   # http://127.0.0.1:8501, then re-run the run-round command
# or each stage alone
$A predict --round r02 --source video --videos ../../input/
$A select --round r02
$A review-status --round r02
$A assemble --round r02
$A evaluate --weights <weights.pt>
# 3. registry, model card, rollback
$A registry                                  # versions, hashes, metrics, champion
$A registry verify
$A registry rollback --to v0001 --reason "night regression at gate 2"
$A model-card                                # registry/models/<version>/MODEL_CARD.md
# 4. deployment artefacts (never applied automatically)
$A export                                    # exports/<version>/: ONNX, OpenVINO, parity report, Frigate snippet
$A propose --round r02 --gate-id GATE-1      # dry run: payloads written privately, masked summary printed
$A ocr-benchmark                             # compare OCR engines on the dev set (never GOLD)
```

## Review app

`anpr review-app --round <id>` binds to 127.0.0.1 with Streamlit telemetry off. Per frame: the proposals (yellow)
with plate crops, the model's read with low-confidence characters in `[ ]`, confusion hints (O/0, I/1, B/8,
S/5, never applied), and track disagreement. Keep or drop boxes, edit coordinates and text, mark a plate
unreadable, add a missed plate, tick **every plate in this frame is boxed**, then *Accept as proposed*,
*Save corrections*, *Reject frame* or *Skip*. Set your name with `ANPR_REVIEWER=<name>` or in the sidebar.

## AWS (nothing runs unless CONFIRM=1)

```bash
make aws-stack BUCKET=campus-anpr-hitl-<account> ALERT_EMAIL=you@example.com          # dry run
make aws-stack BUCKET=... ALERT_EMAIL=... CONFIRM=1      # private SSE-KMS bucket (versioned, retention rule),
                                                         # EC2 role limited to the prefix, ECR repo, budget alerts
make docker-build && make docker-push ECR=<uri> CONFIRM=1
make train-aws ROUND=r03 BUCKET=... KMS_KEY=<arn> IMAGE=<ecr uri:tag> INSTANCE_PROFILE=<name> \
     PRICE_PER_HOUR=<current spot price> EST_HOURS=<estimate>                          # dry run + cost
```

The instance (g6.2xlarge spot, 100 GB gp3, IMDSv2) syncs the data root from the bucket, runs `anpr run-round`
in the container, pushes results back and shuts down (terminate on shutdown). A spot notice makes the trainer
stop at the epoch boundary and pushes the last verified checkpoint; relaunching resumes from it. An idle
watchdog shuts the instance down after 15 minutes without GPU work. Activate the `Project` cost-allocation tag in
Billing for the budget filter to work. Set `s3.enabled`, `s3.bucket` and `s3.kms_key_id` in `config.yaml` to
mirror checkpoints during local training too.

Cost model: hours = images x epochs / (images per second x 3600). Measured locally (RTX 4050 laptop, 1280 px,
batch 4): about 8 images/s. Look up the current g6.2xlarge price before launching.

## Privacy (DPDP Act 2023)

Number plates are personal data. Raw frames, crops, predictions and the audit log stay in the private data root
or the private encrypted bucket (retention rule on frames and rounds); share only blurred copies; the CLI never
prints plate text (proposals show `PB******34`). The review app listens on localhost only.

## Licence

Ultralytics YOLO is **AGPL-3.0**. Fine for academic research; deploying the detector (or a service built on it)
beyond academic use needs an Ultralytics Enterprise licence or publishing the whole service under AGPL-3.0.
RapidOCR / PaddleOCR models are Apache-2.0; fast-plate-ocr is MIT; Tesseract is Apache-2.0.
