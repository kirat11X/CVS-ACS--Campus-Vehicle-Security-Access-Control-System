# Project digest — isolated ML staging track

## Purpose

PEC's Campus Vehicle Security & Access-Control System is a central, PostgreSQL-backed intelligence layer for three perimeter gates. It records camera observations, associates them with registered institutional context where evidence permits, preserves audit history, and surfaces guard-review context. It never actuates a barrier.

## Ten invariants

1. Gate nodes are telemetry collectors, never authoritative state or policy engines.
2. The central server and PostgreSQL are the single authoritative campus state.
3. A plate is an optical token, not an institutional identity.
4. A vehicle is an asset, not a person; ownership is independently modeled.
5. Residence belongs to a person/owner, never to a vehicle.
6. Recording an observation does not create an access decision.
7. Decisions and security actions must trace to observations, identity context, and policy.
8. Historical operational events are never hard-deleted; deactivate instead.
9. ML produces probabilistic perception; deterministic policy produces security outcomes.
10. All three gates contribute to one campus-wide state and timeline.

## Pipeline

Frigate cameras at Gate 1–3 publish telemetry to Mosquitto (`frigate/#`); the FastAPI worker parses and preserves raw observations; PostgreSQL stores registry, identity, delivery and audit context; guard-facing interfaces receive context and alerts. WhatsApp invoices enter through n8n, then the FastAPI invoice/OCR flow. Guards remain the physical and final operational decision makers.

## Stack and ports

| Layer | Technology | Host port | Notes |
|---|---|---:|---|
| API | FastAPI / SQLAlchemy 2 / Python 3.14 | 8000 | authoritative services (v0.7.0, 16 routers) |
| Database | PostgreSQL 16 | 5433 | deliberately not 5432 (19 models, 7 migrations) |
| Broker | Mosquitto 2.1.2 | 1883 | Frigate telemetry bus |
| NVR | Frigate 0.18 | 5000 / 8554 | VAAPI / RTSP |
| Automation | n8n 1.82+ | 5678 | WhatsApp/webhook route |
| Console (Web & Mobile) | React 19 / Vite 6 / Capacitor 7 | 5173 / 4173 | responsive console & Android APK (16 views) |

## Status and schema

Milestone 0 and Phases 1–4, 5A, 5C (live feed SSE), 6 (movements & presence), 7 (delivery screening), 13 (OpenAPI grouping), and 16 (guard & admin console) are complete, passing all integration suites, and hardened across 27 post-audit commits (`964895b` $\rightarrow$ `fd9d677`). Phase 5B (real PEC gate video evaluation), 8/9/10 (multimodal VLM fine-tuning, automated order matching, production Meta credentials), 11/12 (review queue, immutable reason codes), 14 (13 E2E operational scenarios), and 15 (simulation mode) are actively tracked on the roadmap. Existing tables cover users, vehicle owners, vehicles, delivery vehicles, gates, camera lanes, access decisions, entry/exit logs, observation events, observation resolutions, feed events, vehicle link events, delivery orders, invoices, invoice items, delivery decisions, visitors, and health checks.

## Gotchas

- Use host PostgreSQL port **5433**; do not change it back to 5432.
- Fedora bind mounts need the SELinux `:z` suffix for container access.
- Project Python is 3.14; many ML wheels (notably Paddle) are unavailable, hence the separate 3.12 ML venv (`~/ml-assets/campus/.venv-ml`).
- Set `KERAS_BACKEND=torch` for Track A OCR training to avoid local TF 2.21 CUDA initialization errors.
- Frigate input videos must be H.264/AVC1 (`libx264`, `yuv420p`), not generic `mp4v`.
- Candidate migrations must explicitly create PostgreSQL enums with `checkfirst=True`.
- Item taxonomy row count across all evaluation fixtures and reports is standardized on the canonical **320 items** (8 classes, 191 brand/template families).

## Where the ML track plugs in

A) Indian ANPR second-reader OCR plus registry-constrained fuzzy match extends the Phase 5A/5C resolver. Fine-tuned YOLO11n (`mAP50=0.8396`) and PyTorch CRNN OCR (`Acc=63.12%`, `CER=8.51%`) are staged under `weights/`.

B) Invoice line-item extraction is staged on the WhatsApp $\rightarrow$ n8n $\rightarrow$ FastAPI pipeline. The deterministic `InvoiceReconciler` (`Decimal` math) and pure review adapter (`adapter_c.py`) guarantee lossless data transfer. Cloud VLM (`Qwen3-VL-2B-Instruct`) is queued for AWS EC2 `g4dn.xlarge`.

C) Item-to-category classification feeds a deterministic policy table yielding `ALLOW` / `REVIEW` / `ALERT` with ReasonCodes. Qwen3-1.7B QLoRA (`full_c_v1`) achieves 0.841 accuracy / 0.818 macro-F1 on the canonical 320-item taxonomy split. The model outputs only category and confidence; policy remains strictly separate.

## Master Documentation Suite

Refer to the primary documentation suite at the repository root:
- [`WHAT_HAS_BEEN_DONE.md`](../WHAT_HAS_BEEN_DONE.md): Complete audit-verified inventory of completed modules.
- [`WHAT_HAS_TO_BE_DONE.md`](../WHAT_HAS_TO_BE_DONE.md): Comprehensive remaining backlog and AWS EC2 training protocols.
- [`BUG_TESTER.md`](../BUG_TESTER.md): Complete QA guide, bug tester documentation, and 20+ regression checks.
- [`DATASETS_AND_MODELS.md`](../DATASETS_AND_MODELS.md): Exhaustive catalog of datasets, checkpoints, and canonical taxonomies.
- [`ROADMAP.md`](../ROADMAP.md): Phased production deployment roadmap from current state to PEC campus pilot.
