# PEC Campus Vehicle Security — Run Log & Digest (2026-10-20)

## What this is
Central, PostgreSQL-backed intelligence layer for three PEC gates. It observes plates via Frigate/MQTT, associates them with registry context (owner, hosteller/day-scholar, delivery), logs movement, and surfaces context to human guards. It never actuates a barrier (OBSERVE -> ASSOCIATE -> CONTEXTUALIZE -> RECORD -> ALERT).

Core invariants: gate nodes are non-authoritative; plate != identity; vehicle != person; residence belongs to the owner; observation != decision; no hard deletes; ML (probabilistic) is separate from policy (deterministic); three gates share one campus state.

## Run status (Fedora laptop, ~/coding/honours)
| Component | State |
|---|---|
| Docker: postgres (5433), mosquitto (1883), frigate (5000/8554), n8n (5678) | up, postgres healthy |
| Alembic | at head, `alembic check`: no drift |
| Backend (uvicorn, 0.0.0.0:8000) | running; /health, /health/db, /health/mqtt all ok (log: /tmp/backend.log) |
| Frontend (vite dev, 0.0.0.0:5173) | running, HTTP 200 (log: /tmp/frontend.log) — http://192.168.29.189:5173 |

Tests run this session — all passed: Phase 1 models, Phase 2 vehicle API (15), Phase 3 gate observations (20), Phase 4 Frigate MQTT worker (+ real MQTT), Phase 6 movement (14), Phase 16 console API (7), E2E (3 pipelines).
Not run: Phase 5A/5C, OCR, audit regressions, research-track tests.
Caveat: Phase 5C/6/16 scripts start their own uvicorn on :8000; stop the running backend before re-running them.

## Architecture
- backend/app: FastAPI + SQLAlchemy 2 + Pydantic v2 (~5k lines). Routes: auth, users, vehicles, owners, gates, lanes, observations, resolutions, feed, movements, presence, dashboard. Services: identity resolution, direction resolver, movement, feed, Frigate event parser, auth. Workers: MQTT ingest. whatsapp/: provider abstraction.
- frontend: React 19 + Vite 6 + Tailwind; Capacitor 7 wraps it as Android/iOS app. Pages: overview, live feed, presence, movement log, registry, owners, gates & lanes, accounts, system status.
- Data flow: Frigate -> Mosquitto (frigate/#) -> ingest worker -> observations -> identity resolution -> movement/presence -> console. Invoices: WhatsApp -> n8n -> FastAPI -> RapidOCR/Tesseract.

## Roadmap
Done: M0, Phases 1-4, 5A/5C (live feed, auth), 6 (movement/presence/linking), 16 (console).
Open: 5 access-control policy engine, 7-9 delivery orders/invoice matching, 10 WhatsApp, 11 review queue, 12 audit/reason codes, 13 OpenAPI grouping, 14 full E2E suite, 15 simulation mode.

## Research track (research_track/)
- A: Indian ANPR second-reader OCR + registry-constrained fuzzy match (EXACT / FUZZY_CONFIDENT / AMBIGUOUS / NO_MATCH); splits grouped by plate string to avoid near-duplicate leakage.
- B: invoice line-item extraction with a VLM (staged, not approved for training).
- C: QLoRA 1.7B item-category classifier feeding a deterministic ALLOW/REVIEW/ALERT policy table.
- Docs: research.md (22 papers), irl_significance.md, per-track SPECIFICATION/IMPLEMENTATION_REPORT.

## Gotchas
Postgres on 5433 (not 5432); SELinux `:z` on bind mounts; Python 3.14 breaks some ML wheels (separate 3.12 ML venv); Frigate test videos must be H.264/yuv420p; always run `alembic check`.

## Housekeeping
Uncommitted changes in the repo (README, config, auth/owners/vehicles routes, movement_service, etc.); 27 commits total. Docs also in README.md, context.md, PROJECT_ARCHITECTURE.md, SETUP_REPORT.md.
