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
| API | FastAPI / SQLAlchemy 2 / Python 3.14 | 8000 | authoritative services |
| Database | PostgreSQL 16 | 5433 | deliberately not 5432 |
| Broker | Mosquitto 2.1.2 | 1883 | Frigate telemetry |
| NVR | Frigate 0.18 | 5000 / 8554 | VAAPI / RTSP |
| Automation | n8n 1.82+ | 5678 | WhatsApp/webhook route |
| Dashboard (planned) | React/Vite/Tailwind | 3000 | guard contextualization |

## Status and schema

Milestone 0 and Phases 1–5A are complete; 5B (real-data evaluation) and 5C (live integration) remain open, as do later delivery, review, audit and dashboard phases. Existing tables cover users, vehicle owners, vehicles, delivery vehicles, gates, access decisions, entry/exit logs, security alerts, delivery orders, invoices, invoice items, visitors, health checks and observation events.

## Gotchas

- Use host PostgreSQL port **5433**; do not change it back to 5432.
- Fedora bind mounts need the SELinux `:z` suffix for container access.
- Project Python is 3.14; many ML wheels (notably Paddle) are unavailable, hence the separate 3.12 ML venv.
- Frigate input videos must be H.264/AVC1 (`libx264`, `yuv420p`), not generic `mp4v`.
- Candidate migrations must explicitly create PostgreSQL enums with `checkfirst=True`; this staging draft is not applied.

## Where the ML track plugs in

A) Indian ANPR second-reader OCR plus registry-constrained fuzzy match extends the Phase 5A resolver.

B) Invoice line-item extraction is staged on the WhatsApp → n8n → FastAPI pipeline.

C) Item-to-category classification feeds a deterministic policy table yielding `ALLOW` / `REVIEW` / `ALERT` with ReasonCodes. The model outputs only category and confidence; policy remains separate.
