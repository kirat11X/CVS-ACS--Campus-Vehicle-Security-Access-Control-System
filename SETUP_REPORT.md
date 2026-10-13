# Campus Vehicle Security & Access Control System: Environment Setup Report

## 1. System Specifications

* **Operating System:** Fedora Linux 44 (Workstation Edition)
* **Kernel:** `7.1.13-200.fc44.x86_64` (SMP PREEMPT_DYNAMIC)
* **Architecture:** x86_64
* **CPU:** Intel(R) Core(TM) i7-13650HX (14 cores / 20 threads, base 800 MHz, max 4900 MHz)
* **RAM:** 15 GiB Total (7.9 GiB Available, 8.0 GiB Swap)
* **GPU:** NVIDIA GeForce RTX 4050 Laptop GPU (6141 MiB VRAM)
* **NVIDIA Driver:** `610.57.04` (CUDA UMD Version 13.3)
* **Hardware Acceleration Status:** 
  * Host has Intel 13th Gen Iris Xe / UHD iGPU (`/dev/dri/renderD128`) passed into Frigate for VAAPI hardware-accelerated video decoding.
  * NVIDIA GPU is present; `nvidia-container-cli` is not installed on host Fedora, so Docker infrastructure operates in CPU + Intel VAAPI hardware acceleration mode.
* **Available Disk Space:** 81 GiB available on NVMe SSD (`/dev/nvme1n1p4`, 82% used)

---

## 2. Installed Software & Runtimes

| Component | Version | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Python** | 3.14.7 | **PASS** | Isolated `.venv` created and configured |
| **Docker** | 29.7.2, build 1.fc44 | **PASS** | Daemon active, tested with `hello-world` |
| **Docker Compose** | 5.5.0 | **PASS** | Orchestrating all 4 containerized services |
| **Node.js** | v24.8.0 | **PASS** | Ready for frontend when needed |
| **npm** | 11.10.0 | **PASS** | Ready for frontend dependencies |
| **FFmpeg** | 8.1.2 | **PASS** | Native host binary + container ffmpeg 7/8 |
| **PostgreSQL** | 16.15 (Alpine) / psql 18.6 | **PASS** | Containerized on port 5433, psql on host |
| **MQTT** | Mosquitto 2.1.2 | **PASS** | Containerized on port 1883, clients present |
| **Frigate** | 0.18.0-77a66e7 | **PASS** | LPR models cached, VAAPI decoding active |
| **n8n** | 1.82+ | **PASS** | Workflow automation & webhook listener |
| **OCR** | Tesseract 5.5.3 + RapidOCR (PP-OCRv4) | **PASS** | Dual-engine OCR verified on Python 3.14 |

---

## 3. Services Status

| Service | URL / Port | Container Name | Health Status |
| :--- | :--- | :--- | :--- |
| **Frigate NVR** | `http://localhost:5000` (API/UI), `8554` (RTSP) | `campus_frigate` | **HEALTHY** (Active 5.0 FPS on `gate_cam`, LPR enabled) |
| **Mosquitto MQTT** | `mqtt://localhost:1883` | `campus_mosquitto` | **HEALTHY** (Accepting pub/sub, Frigate publishing) |
| **PostgreSQL** | `localhost:5433` (`campus_security`) | `campus_postgres` | **HEALTHY** (Dev user `campus_admin`, migrations OK) |
| **FastAPI Backend** | `http://localhost:8000` | Local `.venv` | **HEALTHY** (`/health`, `/health/db`, `/health/mqtt` 200 OK) |
| **n8n Automation** | `http://localhost:5678` | `campus_n8n` | **HEALTHY** (Webhook active and processing) |

---

## 4. Verification Test Results

| Test Case | Scope / Component Tested | Result | Details |
| :--- | :--- | :--- | :--- |
| **Docker Engine Test** | Docker daemon & hub registry | **PASS** | Executed `hello-world` container and network egress |
| **PostgreSQL Connection Test** | SQLAlchemy & psycopg on port 5433 | **PASS** | Connected, queried version, created `health_checks` table |
| **MQTT Pub/Sub Test** | Mosquitto message roundtrip | **PASS** | Verified publisher → broker → subscriber on `test/topic` |
| **FastAPI Health Test** | FastAPI baseline endpoints | **PASS** | `GET /health`, `/health/db`, `/health/mqtt`, `/health/all` returned 200 OK |
| **OCR Test** | Independent invoice text extraction | **PASS** | RapidOCR & Tesseract extracted order ID `#ORD-2026-9821` |
| **Frigate Startup Test** | Frigate container & web service | **PASS** | Booted without errors, API responding at `http://localhost:5000` |
| **Frigate LPR Test** | License Plate Recognition subsystem | **PASS** | Downloaded YOLOv9 LPR & PaddleOCR ONNX models, enabled on `gate_cam` |
| **MQTT → Frigate Event Test**| Frigate camera telemetry to MQTT | **PASS** | Captured 20+ live events on `frigate/#` (`gate_cam`, `motion`, `available`) |
| **n8n Webhook Test** | Webhook JSON receipt and response | **PASS** | `POST http://localhost:5678/webhook/test-invoice` returned HTTP 200 |
| **End-to-End Pipeline 1** | Video → Frigate → MQTT → FastAPI → DB | **PASS** | Simulated plate `DL 01 AB 1234` logged to PostgreSQL record #3 |
| **End-to-End Pipeline 2** | Invoice Image → OCR → Backend → DB | **PASS** | Synthetic invoice extracted & stored in PostgreSQL record #4 |
| **End-to-End Pipeline 3** | Webhook → n8n → Backend | **PASS** | Webhook triggered n8n and forwarded to FastAPI successfully |
| **External WhatsApp API** | Meta Cloud API / WhatsApp Gateway | **BLOCKED** | External credentials required (Mock provider active for local dev) |

---

## 5. Detailed Analysis of FAIL / BLOCKED Items

### External WhatsApp API Integration

1. **What is Blocked:**
   Real Meta WhatsApp Cloud API credentials and live webhook endpoints (`WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`).
2. **Why it is Blocked:**
   Live WhatsApp integration requires an official Meta Business Account, registered phone number, and cloud callback webhook. These external credentials have not yet been provisioned for local development.
3. **Exact Log / Responsible Component:**
   `backend/app/whatsapp/mock.py` and `.env` contain placeholder keys: `WHATSAPP_API_TOKEN=mock_token_for_local_dev`.
4. **Resolution Required:**
   When ready for staging/production deployment, provide Meta WhatsApp Cloud API tokens in `.env` and configure public webhook tunneling (e.g. ngrok / Cloudflare Tunnel) to forward incoming messages to n8n / FastAPI.
5. **Does this Block the Project?**
   **NO.** Per Phase 10 guidelines, the modular `WhatsAppProvider` abstraction with `MockWhatsAppProvider` allows the entire invoice processing and webhook flow to be built and thoroughly tested offline without external credentials.

---

## 6. Architecture Decisions & Configuration Details

1. **PostgreSQL Port 5433:**
   The host machine was running a personal PostgreSQL instance on native port 5432. To maintain isolation and avoid interfering with host configurations, the project PostgreSQL Docker container is mapped to `5433:5432`. Application configuration and `.env` point to port 5433.
2. **SELinux Volume Relabeling:**
   On Fedora Linux 44, SELinux prevents unprivileged container users (such as Mosquitto UID 1883 and Frigate) from accessing mounted workspace directories without the `:z` shared mount flag. All bind mounts in `docker-compose.yml` include `:z` for SELinux compliance.
3. **Hardware Acceleration:**
   Host Intel UHD graphics (`/dev/dri/renderD128`) was mounted into Frigate, enabling VAAPI hardware-accelerated video decoding at 0.74% GPU load. NVIDIA GPU remains available on host, while containers operate stably without requiring external toolkit modifications.
4. **OCR Dual Engine on Python 3.14:**
   Because upstream PaddlePaddle does not yet distribute binary wheels for Python 3.14, the project implements RapidOCR (ONNXRuntime-based PP-OCRv4 model) alongside native Tesseract 5.5 (`pytesseract`). Both engines passed text recognition on test invoices.

---

## 7. Phase 1: Database Models & Alembic Migrations

* **Status:** **PASS**
* **Migration Revision:** `3e3fa78436be_create_initial_campus_security_schema.py`
* **Applied via:** `alembic upgrade head`
* **Tables Created (14 tables in PostgreSQL):**
  1. `users`: System user and security guard accounts.
  2. `vehicle_owners`: Students, faculty, staff, and campus residents.
  3. `visitors`: Registered campus guests with validity windows and host associations.
  4. `vehicles`: Vehicle records with `raw_plate` and unique indexed `normalized_plate`.
  5. `delivery_vehicles`: Fleet driver profiles for delivery aggregators.
  6. `gates`: Campus gates (GATE_1, GATE_2, GATE_3) with Frigate camera mappings.
  7. `access_decisions`: Immutable audit trail for every access evaluation.
  8. `entry_exit_logs`: Physical gate crossing event log with direction, confidence, and timestamps.
  9. `security_alerts`: Escalation queue for guards and administrators.
  10. `delivery_orders`: Delivery orders with platform, customer, and verification status.
  11. `invoices`: Processed invoice OCR metadata and financial totals.
  12. `invoice_items`: Individual invoice line items.
  13. `alembic_version`: Alembic migration state tracker.
  14. `health_checks`: Continuous infrastructure probe records.
* **Verification Suite:** `scripts/test_phase1_models.py` (11/11 tests passed, verifying all CRUD operations, foreign keys, unique plate constraints, and ORM relationship navigation).

---

## 8. Phase 2: Vehicle Registry & Identity Association API

* **Status:** **PASS**
* **Migration Revision:** `9e13fe119fc4_add_vehicle_identity_context.py`
* **Applied via:** `alembic upgrade head`
* **Architectural Concept:**
  - The central server is the authoritative campus intelligence layer; gates are distributed observation points without independent business logic.
  - Institutional Identity Resolution Pipeline:
    `PLATE → VEHICLE → OWNER (VehicleOwner) → INSTITUTIONAL IDENTITY (PersonType) → RESIDENCE CONTEXT (ResidenceType: HOSTELLER/DAY_SCHOLAR, residence: BH-4)`
  - Residence context strictly belongs to the person (`VehicleOwner`), not the vehicle.
* **Models Extended:**
  - `backend/app/models/enums.py`: Added `PersonType` (`STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`) and `ResidenceType` (`HOSTELLER`, `DAY_SCHOLAR`, `OFF_CAMPUS`, `UNKNOWN`).
  - `backend/app/models/identity.py`: Added `person_type`, `residence_type`, `residence`, and `department` fields to `VehicleOwner`.
* **Services Created:**
  - `backend/app/services/plate_normalizer.py`: Standardizes raw plate strings to uppercase alphanumeric (`normalize_plate`) and formats display strings (`format_plate_display`).
  - `backend/app/services/vehicle_identity_service.py`: Encapsulates authoritative vehicle-to-owner resolution (`resolve()`, `get_owner_for_vehicle()`, `is_vehicle_active()`, `get_residence_context()`).
* **Endpoints Implemented:**
  - `POST /vehicles`: Register vehicle with identity association, automatic plate normalization, and 409 duplicate check.
  - `GET /vehicles`: Filterable listing (`category`, `status`, `skip`, `limit`).
  - `GET /vehicles/{plate}`: Deep identity & residence context resolution, format-tolerant plate lookup.
  - `PUT /vehicles/{plate}`: Safe metadata updates (color, make/model, validity, notes); plate mutation explicitly rejected (HTTP 400).
  - `DELETE /vehicles/{plate}`: Soft deactivation (`status = INACTIVE`) ensuring complete audit trail preservation.
* **Verification Suite:**
  - `scripts/test_phase2_vehicle_api.py`: 15/15 scenarios passed.
  - Regression: Phase 1 models test (11/11 passed), FastAPI health suite (all passed), E2E integration pipelines (all 3 passed).

---

## 9. Phase 3: Gate Registry & Gate Observation Management

* **Status:** **PASS**
* **Migration Revision:** `1c9f9a684531_add_observation_events_and_gate_status.py`
* **Applied via:** `alembic upgrade head`
* **Alembic Drift Check (`.venv/bin/alembic check`):** **PASS** (`No new upgrade operations detected.`, Exit Code 0)
* **Architectural Realignment:**
  - Explicitly established that the software is a **vehicle security management and intelligence system**, NOT an automated barrier controller.
  - Physical gates at Punjab Engineering College (PEC) are operated by authorized human security guards.
  - The software observes, associates, contextualizes, records, and alerts.
  - Invariant verified: `OBSERVATION ≠ DECISION`. Ingesting an observation creates zero access decisions.
  - Separated physical sensor perception (`ObservedVehicleType`: `CAR`, `MOTORCYCLE`, etc.) from institutional identity (`VehicleCategory`: `STUDENT`, `DELIVERY`, etc.).
  - Non-judgmental stance: `UNKNOWN ≠ THREAT`.
* **Models Added / Extended:**
  - `backend/app/models/enums.py`: Extended `GateStatus` with `'INACTIVE'`. Added `ObservationSource`, `ObservedVehicleType`, `ObservationDirection`.
  - `backend/app/models/observation.py`: Created `ObservationEvent` table with indexes and idempotency support.
  - `backend/app/models/gate.py`: Added relationship `observations` to `Gate`.
* **Services & Schemas:**
  - `backend/app/services/observation_service.py`: Deduplication and idempotency layer using `source_event_id`. Re-ingested Frigate events refine existing records rather than creating duplicate rows.
  - `backend/app/schemas/gate.py`: `GateCreate`, `GateUpdate`, `GateResponse`.
  - `backend/app/schemas/observation.py`: `ObservationCreate`, `ObservationResponse` (structured sensory output without `decision`, `threat`, or `owner`).
* **Endpoints Implemented:**
  - `GET /gates`: List all campus gates with optional `?status=...` filter.
  - `GET /gates/{gate_id}`: Retrieve gate configuration and camera mapping.
  - `POST /gates`: Register gate (409 Conflict if already exists).
  - `PUT /gates/{gate_id}`: Update gate location, camera ID, or operational status.
  - `DELETE /gates/{gate_id}`: Safe soft-deactivation (`status = INACTIVE`).
  - `GET /gates/{gate_id}/observations`: List observations captured at a specific gate.
  - `POST /observations`: Controlled ingestion of camera/sensor observations.
  - `GET /observations`: Filterable observation log (`?gate_id=...`, `?plate=...`, `?source=...`).
  - `GET /observations/{id}`: Detailed observation payload.
  - `GET /vehicles/{plate}/observations`: Retrieve all observations for a license plate (format-tolerant).
* **Verification Suite:**
  - `scripts/test_phase3_gate_observations.py`: **20/20 scenarios passed**.
  - Regression: Phase 1 models test (11/11 passed), Phase 2 vehicle API (15/15 passed), FastAPI health suite (all passed), E2E integration pipelines (all 3 passed), Alembic check (0 drift).

### Verified Test Scenarios (20/20 PASS):
| Scenario | Scope | Result | Details |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | Register GATE_1 | **PASS** | Created `GATE_1` (Main North Gate, camera `gate_cam`, 409 on duplicate) |
| **Scenario 2** | Register GATE_2 | **PASS** | Created `GATE_2` (South Campus Gate, camera `gate_2_cam`, 409 on duplicate) |
| **Scenario 3** | Register GATE_3 | **PASS** | Created `GATE_3` (Hostel East Gate, camera `gate_3_cam`, 409 on duplicate) |
| **Scenario 4** | List configured gates | **PASS** | `GET /gates` returned all configured campus gates |
| **Scenario 5** | Retrieve gate by ID | **PASS** | `GET /gates/GATE_1` retrieved configuration and camera mapping |
| **Scenario 6** | Update gate metadata | **PASS** | `PUT /gates/GATE_1` updated location and operational metadata |
| **Scenario 7** | Gate status transitions | **PASS** | Transitioned `ACTIVE` → `MAINTENANCE` → `ACTIVE` |
| **Scenario 8** | Ingest Frigate observation | **PASS** | `POST /observations` recorded raw detection event with metadata |
| **Scenario 9** | Plate normalization | **PASS** | Normalized `pb 65 ab 0902` to `PB65AB0902` |
| **Scenario 10** | Raw plate preservation | **PASS** | Preserved exact optical string `pb 65 ab 0902` |
| **Scenario 11** | LPR confidence preservation | **PASS** | Preserved optical confidence score `0.94` |
| **Scenario 12** | Perception vs. Identity | **PASS** | `ObservedVehicleType.MOTORCYCLE` stored; no institutional category in observation |
| **Scenario 13** | Source event ID tracking | **PASS** | Preserved Frigate tracking token `source_event_id` |
| **Scenario 14** | Query gate observations | **PASS** | `GET /gates/GATE_1/observations` returned gate-specific events |
| **Scenario 15** | Format-tolerant plate query | **PASS** | `GET /vehicles/pb-65-ab-0902/observations` successfully queried normalized plate |
| **Scenario 16** | Unknown plate handling | **PASS** | Ingested unregistered plate without auto-creating `Vehicle` (`UNKNOWN ≠ THREAT`) |
| **Scenario 17** | Unknown direction handling | **PASS** | Handled `ObservationDirection.UNKNOWN` cleanly |
| **Scenario 18** | Deduplication & Idempotency | **PASS** | Re-posting same `source_event_id` refined existing record (confidence 0.94 → 0.98, single DB row) |
| **Scenario 19** | Historical persistence | **PASS** | `DELETE /gates/{id}` soft-deactivated gate (`status=INACTIVE`); observations remained queryable |
| **Scenario 20** | Invariant: Observation ≠ Decision | **PASS** | Ingested observation created 0 `AccessDecision` records; response contained no `decision`, `threat`, or `owner` |

---

## 10. Phase 4: Frigate MQTT Observation Ingestion Worker

* **Status:** **PASS**
* **Alembic Drift Check (`.venv/bin/alembic check`):** **PASS** (`No new upgrade operations detected.`, Exit Code 0)
* **Architectural Scope & Boundaries:**
  - Implemented persistent background worker (`FrigateMQTTWorker`) consuming MQTT telemetry on `frigate/events`.
  - Implemented translation layer (`FrigateEventParser`) mapping Frigate event payloads into `ObservationCreate` schemas.
  - Camera $\rightarrow$ Gate Resolution: Queries `Gate` by `camera_id` (e.g. `gate_cam` $\rightarrow$ `GATE_1`). Unknown cameras are quarantined/logged; never defaults to `GATE_1`.
  - Vehicle Type Mapping: Maps physical labels (`car`, `motorcycle`, `bus`, `truck`) to `ObservedVehicleType`. Unrecognized labels map to `UNKNOWN`.
  - LPR Plate Extraction: Extracts raw plate, extracts confidence score, and normalizes plate via `normalize_plate`. Missing plates are preserved as observations with `raw_plate=None`.
  - Strict Direction Invariant: Direction is set to `ObservationDirection.UNKNOWN` (no simplistic `camera == gate_cam -> ENTRY` inference).
  - Idempotency & Refinement: Uses `source_event_id` to refine existing `ObservationEvent` records across video tracking frames without row duplication.
  - Invariants Enforced:
    - `OBSERVATION ≠ DECISION`: 0 access decisions created.
    - `OBSERVATION ≠ THREAT`: Unknown plates stored as observation without threat flag.
    - `PLATE ≠ IDENTITY`: No auto-creation of `Vehicle` or `VehicleOwner` records.
    - `NO BARRIER CONTROL`: No GPIO, barrier actuation, or open/close logic.
* **Components Created / Modified:**
  - `backend/app/services/frigate_event_parser.py`: Dedicated translation layer.
  - `backend/app/workers/frigate_mqtt_worker.py`: Background MQTT worker with automatic reconnect, error containment, and telemetry tracking.
  - `backend/app/workers/__init__.py`: Exported worker singleton.
  - `backend/app/main.py`: Integrated `frigate_worker.start()` and `frigate_worker.stop()` into FastAPI lifespan; exposed worker stats in `GET /health/all` and `GET /api/workers/frigate-worker`.
  - `config/frigate/config.yml`: Added `objects: track: [car, motorcycle, bus, truck, person]` under `gate_cam`.
* **Verification Suite (`scripts/test_phase4_frigate_mqtt_worker.py`):** **20/20 PASS + Real MQTT Integration PASS**.
  - Regression: Phase 1 models test (11/11 passed), Phase 2 vehicle API (15/15 passed), Phase 3 gate observations (20/20 passed), FastAPI health suite (all passed), E2E integration pipelines (all 3 passed), Alembic check (0 drift).

### Verified Test Scenarios (20/20 PASS):
| Scenario | Scope | Result | Details |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | Valid Frigate event ingestion | **PASS** | `process_payload()` ingested standard Frigate `after` payload into `ObservationEvent` |
| **Scenario 2** | Plate normalization | **PASS** | Normalized `PB 65 AB 0902` to `PB65AB0902` |
| **Scenario 3** | Raw plate preservation | **PASS** | Preserved exact optical string `PB 65 AB 0902` |
| **Scenario 4** | LPR confidence preservation | **PASS** | Preserved optical confidence score `0.94` |
| **Scenario 5** | Vehicle type mapping | **PASS** | Mapped `car` $\rightarrow$ `CAR`, `motorcycle` $\rightarrow$ `MOTORCYCLE`, `bus` $\rightarrow$ `BUS`, `truck` $\rightarrow$ `TRUCK` |
| **Scenario 6** | Unknown vehicle type | **PASS** | Mapped unsupported label to `ObservedVehicleType.UNKNOWN` |
| **Scenario 7** | Missing plate handling | **PASS** | Handled detection without plate (`raw_plate=None`, `normalized_plate=None`) |
| **Scenario 8** | Unknown/unregistered plate | **PASS** | Ingested unregistered plate without auto-creating `Vehicle` (`UNKNOWN ≠ THREAT`) |
| **Scenario 9** | Camera $\rightarrow$ Gate resolution | **PASS** | Resolved camera `gate_2_cam` to gate `GATE_2` |
| **Scenario 10** | Unknown camera handling | **PASS** | Quarantined/skipped unmapped camera without assigning to default gate |
| **Scenario 11** | `source_event_id` preservation | **PASS** | Preserved Frigate tracking token `source_event_id` |
| **Scenario 12** | Duplicate event idempotency | **PASS** | Re-ingested duplicate payload returned existing ID; exact 1 row in DB |
| **Scenario 13** | Event refinement/update | **PASS** | Re-posted event with higher confidence (0.71 $\rightarrow$ 0.98) refined record; 1 row in DB |
| **Scenario 14** | Malformed JSON handling | **PASS** | Caught non-JSON byte stream safely without worker crash; incremented error counter |
| **Scenario 15** | Incomplete Frigate payload | **PASS** | Caught payload missing ID/camera safely without worker crash |
| **Scenario 16** | UNKNOWN direction enforcement | **PASS** | Strictly enforced `direction = ObservationDirection.UNKNOWN` |
| **Scenario 17** | Invariant: Observation $\neq$ Decision | **PASS** | AccessDecision table count unchanged before and after ingestion |
| **Scenario 18** | Invariant: Vehicle registry immutability | **PASS** | Vehicle and VehicleOwner table counts unchanged before and after ingestion |
| **Scenario 19** | MQTT disconnect/reconnect resilience | **PASS** | Managed broker disconnect and re-established active subscription state |
| **Scenario 20** | Graceful worker shutdown | **PASS** | Worker stopped loop and disconnected cleanly |
| **Integration** | Real Mosquitto MQTT Pipeline | **PASS** | Published to `frigate/events` on port 1883; consumed by worker; persisted in PostgreSQL |

---

## 11. Phase 5C: Live Plate Feed, Registry Linkage & Manual Entry

* **Status:** **PASS**
* **Migration Revision:** `d529411fb6a3_add_manual_observations_guard_resolutions_and_feed.py` (down revision `1c9f9a684531`)
* **Applied via:** `alembic upgrade head`; downgrade → upgrade round trip verified
* **Alembic Drift Check (`.venv/bin/alembic check`):** **PASS** (`No new upgrade operations detected.`)
* **Scope:** Guard dashboard shows each observation live with its registry linkage; guards can register a visitor/delivery vehicle, log a manual sighting, and confirm or reject fuzzy candidates. Context and flags only: 0 access decisions, no barrier/GPIO code, nothing labelled THREAT.
* **Schema:**
  - `observation_source_enum`: `'MANUAL'` already existed (created by `1c9f9a684531`); the migration re-asserts it with `ADD VALUE IF NOT EXISTS`.
  - `observation_events.created_by_id`, `observation_events.note`, `vehicles.created_by_id`, `vehicle_owners.created_by_id`.
  - `observation_resolutions` (append-only; trigger `observation_resolutions_append_only` rejects UPDATE/DELETE) with `resolution_outcome_enum`.
  - `observation_feed_events` (BIGSERIAL cursor log) with `feed_event_kind_enum`.
* **Backend components:** `dependencies.py`, `services/auth_service.py`, `services/plate_similarity.py`, `services/identity_resolution_service.py`, `services/feed_events.py`, `services/feed_service.py`, `routes/auth.py`, `routes/owners.py`, `routes/feed.py`, `routes/resolutions.py`, `schemas/feed.py`, `schemas/owner.py`; modified `ObservationService` (feed events, `create_manual_observation`), `VehicleIdentityService` (`build_context` / `build_owner_context` extracted, `resolve()` unchanged), `routes/vehicles.py` (auth + registration policy + feed re-emission), `routes/observations.py`, `main.py` (v0.5.0), `config.py`.
* **Endpoints:** `POST /auth/login`, `GET /auth/me`, `GET /feed`, `GET /feed?since_id=`, `GET /feed/stream` (SSE), `GET /feed/snapshots/{observation_id}` (Frigate snapshot proxy), `POST /observations/manual`, `POST /resolutions`, `GET /owners?q=`, `POST /owners`.
* **Behaviour change:** `POST /vehicles` now requires authentication; `PUT`/`DELETE /vehicles/{plate}` require ADMIN; `POST /observations` rejects `source=MANUAL`. The Phase 2 suite now logs in as an ADMIN (no assertions changed).
* **Frontend:** `frontend/` (React 19.3, Vite 6.4, Tailwind 3.4, TypeScript 5.9). Live feed cards for the five link states (neutral palette; NOT_LINKED is slate, not red), authenticated snapshot, raw and normalized plate, confidence, gate, time, direction shown as Unknown when unknown, registry status verbatim. Register-vehicle modal (owner search; owner creation for ADMIN; validity window for visitor/delivery), manual entry modal (guard picks direction), Confirm / None of these. SSE over `fetch` (bearer header) with reconnect back-off, polling fallback after 2 failed attempts, and a Live / Reconnecting / Polling / Offline indicator. `npm run typecheck` and `npm run build` pass; SSE verified through the Vite `/api` proxy.

### Verified Test Scenarios (`scripts/test_phase5c_live_feed.py`, 16/16 PASS)
| Scenario | Scope | Result | Details |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | Authentication | **PASS** | 3 roles log in; wrong password, inactive account, forged/garbage tokens → 401 |
| **Scenario 2** | Auth enforcement | **PASS** | 7 endpoints return 401 without a token (feed, stream, manual, resolutions, vehicles, owners) |
| **Scenario 3** | Registry fixtures | **PASS** | ADMIN creates owner (HOSTELLER, BH-4) and ACTIVE / SUSPENDED / BLACKLISTED / expired-window vehicles via API |
| **Scenario 4** | `LINKED` | **PASS** | Confident exact read → vehicle, owner, residence (from owner), `EXACT_PLATE`, direction UNKNOWN |
| **Scenario 5** | `LINKED_INACTIVE` | **PASS** | SUSPENDED, BLACKLISTED (verbatim) and expired window (`VALIDITY_ENDED`); no THREAT label |
| **Scenario 6** | `NOT_LINKED` | **PASS** | Unregistered plate; confident near-miss gets no fuzzy suggestions |
| **Scenario 7** | `LOW_CONFIDENCE` | **PASS** | OCR-confused read @0.55 → scored suggestions (0.95), not applied; exact plate @0.50 also not auto-linked |
| **Scenario 8** | `NO_PLATE` | **PASS** | Detection without plate |
| **Scenario 9** | No auto-creation | **PASS** | Vehicle / VehicleOwner / Visitor counts unchanged by ingestion and resolution |
| **Scenario 10** | Update in place | **PASS** | Same `source_event_id`: 1 row, 1 feed item, `OBSERVATION_UPDATED`, LOW_CONFIDENCE → LINKED |
| **Scenario 11** | Manual observation | **PASS** | `source=MANUAL`, `created_by`, guard direction, no camera/confidence; all test camera rows byte-identical; 404/400/422 validation; generic MANUAL ingest → 400 |
| **Scenario 12** | Append-only resolution | **PASS** | Two resolutions kept, latest shown, observation row unchanged; raw SQL UPDATE/DELETE and ORM update rejected |
| **Scenario 13** | Permission matrix | **PASS** | GUARD/SUPERVISOR permanent categories 403; window missing/too long/past 400; duplicate 409; ADMIN 201; owners create ADMIN-only; PUT/DELETE ADMIN-only; soft delete keeps row |
| **Scenario 14** | SSE | **PASS** | `ready`, then pushes for new observation, refinement (same item), guard registration (`REGISTRY_UPDATED` → LINKED) and resolution; `Last-Event-ID` resume |
| **Scenario 15** | Polling fallback | **PASS** | `since_id` + `has_more` paging at `limit=1` delivers all changes |
| **Scenario 16** | Invariants | **PASS** | AccessDecision / EntryExitLog / SecurityAlert counts unchanged; no decision/threat/access/barrier keys in feed payloads |

* **Regression:** OCR, FastAPI health, Frigate MQTT, E2E (3 pipelines), Phase 1 (all checks), Phase 2 (15/15), Phase 3 (20/20), Phase 4 (20/20), Phase 5A (27/27): all PASS. Alembic check: 0 drift.
* **Open items:** `RESOLUTION_CONFIDENCE_THRESHOLD` (0.80) and suggestion similarity (0.70) are unvalidated starting values pending Phase 5B on real PEC footage; fuzzy candidates are scanned in Python per request (fine at current registry size, revisit with pg_trgm at scale); `observation_feed_events` has no retention policy yet; existing read endpoints (`GET /vehicles`, `GET /observations`) and `POST /observations` remain unauthenticated as in Phases 2–3.

---

## 12. Phase 6: Entry/Exit Movement Logging, Direction Provenance, Presence & Owner Linking

* **Status:** **PASS** (synthetic Frigate payloads; real-footage direction not validated, see open items)
* **Migration Revision:** `0453af6c03f6_add_movement_logging_lanes_and_link_events.py` (down revision `d529411fb6a3`)
* **Applied via:** `alembic upgrade head`; downgrade → upgrade round trip verified
* **Alembic Drift Check:** **PASS** (`No new upgrade operations detected.`)
* **Invariant amendment (context.md, PROJECT_ARCHITECTURE.md):** a declared camera lane role or zone order is configuration entered by an administrator, not inference; direction never comes from camera/gate names; otherwise UNKNOWN and no movement is logged.
* **Schema:** `camera_lanes`; `vehicle_link_events` (append-only trigger); `entry_exit_logs` provenance columns + nullable plate/decision columns + append-only trigger for movement rows; enums `lane_role_enum`, `direction_method_enum`, `log_plate_source_enum`, `link_method_enum`; `feed_event_kind_enum` + `MOVEMENT_UPDATED`.
* **Backend components:** `services/direction_resolver.py`, `services/movement_lookup.py`, `services/movement_service.py`, `services/vehicle_registration_service.py` (extracted from `routes/vehicles.py`, behaviour unchanged), `services/vehicle_link_service.py`, `models/movement.py`, `schemas/movement.py`, `routes/lanes.py`, `routes/movements.py`, `routes/presence.py`; modified `models/gate.py` (EntryExitLog), `ObservationService` (movement hook), `FrigateEventParser` (lane camera → gate), `IdentityResolutionService` (direction/movement on feed items, `with_suggestions`/`with_movement` options), `routes/vehicles.py` (link, history), `main.py` (v0.6.0), `config.py`.
* **Endpoints:** `GET /lanes`, `PUT /lanes/{camera_id}` (ADMIN), `GET /logs`, `GET /logs/{id}`, `POST /logs/confirm`, `POST /logs/{id}/corrections`, `GET /presence`, `GET /presence/inside`, `GET /vehicles/{plate}/history`, `POST /vehicles/{plate}/link`. All require an authenticated GUARD/SUPERVISOR/ADMIN.
* **Frontend:** navigation (Live feed, Inside campus, Movement log, Vehicle history) with the live stream kept connected across pages; feed cards show "Entered campus / Left campus · method", Confirm entry/exit when unknown, Correct, Link to owner, History; correction and link-to-owner modals (minimal PII notice, evidence required). `npm run typecheck`/`build` pass; page endpoints verified through the Vite proxy. A visual browser check was not possible (Chrome extension not connected).
* **5C suite adjustment:** Scenario 16 now counts `entry_exit_logs` rows *with an access decision* (unchanged), because guard manual entries with ENTRY/EXIT now correctly create movement rows.

### Verified Test Scenarios (`scripts/test_phase6_movement.py`, 14/14 PASS)
| Scenario | Scope | Result | Details |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | Lane configuration | **PASS** | ADMIN declares 5 lanes; GUARD/SUPERVISOR 403; invalid zone combos 400; unknown gate 404; camera of another gate 409 |
| **Scenario 2** | Camera-role direction | **PASS** | ENTRY_LANE → ENTRY, EXIT_LANE → EXIT (`CAMERA_ROLE`, lane evidence); camera → gate via lane; observation direction still UNKNOWN; no decision on rows |
| **Scenario 3** | Zone order + no name inference | **PASS** | outside→inside ENTRY, inside→outside EXIT (`ZONE_ORDER`); single zone waits for a later update; camera named `*_entry_cam` without zones and unconfigured `gate_cam` → UNKNOWN, no movement |
| **Scenario 4** | Guard confirmation | **PASS** | UNKNOWN → no log; Confirm creates `GUARD_CONFIRMED` root by the guard; observation byte-identical; second confirm 409; feed `MOVEMENT_UPDATED` |
| **Scenario 5** | Idempotency & debounce | **PASS** | 3 updates of one event → 1 movement; repeat 20 s later → `REPEAT_NOT_LOGGED`; 120 s later → new movement; opposite direction logged |
| **Scenario 6** | No plate | **PASS** | plate NULL + `NO_PLATE`, listed as unattributed entry; guard plate = correction row; original unchanged |
| **Scenario 7** | Corrections | **PASS** | direction then plate correction → 3 rows, all `correction_of_id` = root; effective view latest; no-op correction 400 |
| **Scenario 8** | Refinement precedence | **PASS** | camera plate refinement appends a system correction; after a guard plate correction later camera reads are ignored |
| **Scenario 9** | Presence & flags | **PASS** | OUTSIDE; OUTSIDE + `EXIT_WITHOUT_ENTRY`; INSIDE + `ENTRY_WHILE_INSIDE`; INSIDE + `LONG_STAY`; registered-without-movement UNKNOWN; inside list includes unlinked plates; no threat/violation wording |
| **Scenario 10** | `GET /logs` filters | **PASS** | plate, direction, gate, date range, linked/unlinked, skip/limit |
| **Scenario 11** | Cross-gate history | **PASS** | GATE_2 entry, GATE_1 sighting (direction unknown), GATE_3 exit in one timeline; presence OUTSIDE |
| **Scenario 12** | Owner linking | **PASS** | GUARD temporary link with new STUDENT owner (`GUARD_VERIFIED_ID`, expiry); past movement and sighting resolve to the owner on read; rows unchanged; 409/403/400/422 cases; ADMIN permanent link to same owner (2 vehicles, residence on owner); link events append-only at DB level |
| **Scenario 13** | Permission matrix | **PASS** | 10 endpoints 401 without token; staff roles can read and confirm/correct |
| **Scenario 14** | Invariants | **PASS** | 26 movement rows written all still present; raw UPDATE/DELETE and ORM update rejected; 0 AccessDecision rows created; no decision-carrying logs created |

* **Regression:** OCR, FastAPI health, Frigate MQTT, E2E, Phase 1 (all checks), Phase 2 (15/15), Phase 3 (20/20), Phase 4 (20/20), Phase 5A (27/27), Phase 5C (16/16): all PASS. Alembic check: 0 drift.

### Open items / PEC data required
* **Direction on real footage is unvalidated.** The test video has no known lane geometry. Needed from PEC: per gate, which physical lanes each camera covers and their traffic direction (for `ENTRY_LANE`/`EXIT_LANE`); for two-way cameras, representative frames to draw `road_side`/`campus_side` zone polygons; 1–2 h of labelled footage per gate (vehicle, true direction, timestamp) to measure ZONE_ORDER accuracy and Frigate `entered_zones` ordering on this Frigate version; guard-recorded ground truth for a sample shift to measure missed/duplicate movements.
* **Starting values to recalibrate:** `MOVEMENT_DEBOUNCE_SECONDS=60`, `PRESENCE_LONG_STAY_HOURS=24`, `PRESENCE_UNATTRIBUTED_LOOKBACK_HOURS=24`.
* **Policy questions:** should a guard be able to void a false movement (e.g. vehicle turned around before the barrier)? Only direction/plate corrections exist today. Should guards create time-limited links for STUDENT/FACULTY/STAFF categories (currently they link such owners via a VISITOR-category vehicle with expiry)? Should `PUT /vehicles` owner changes also write a `VehicleLinkEvent`?
* **Scale:** presence/logs/history recompute over all movement records per request; move aggregation into SQL (or a derived table rebuilt from the append-only log) before production volumes.
