# Context & System Blueprint for Future LLMs / Developers

> **Purpose:** This file serves as the definitive source of truth and onboarding context for any AI assistant, LLM, or software engineer working on this repository. Read this file completely before making any modifications to the codebase, dependencies, or infrastructure.

---

## 1. Project Overview & Objective

* **System Name:** Campus Vehicle Security & Access-Control System
* **Domain:** University campus gate security across 3 gates (`GATE_1`, `GATE_2`, `GATE_3`).
* **Core Capabilities:**
  1. Camera-based vehicle license plate recognition (ANPR / LPR) via Frigate NVR.
  2. Telemetry ingestion from Frigate into a FastAPI backend via Mosquitto MQTT.
  3. Relational audit & identity persistence in PostgreSQL 16.
  4. Vehicle categorization: Student, Faculty, Staff, Resident, Visitor, Delivery (Zomato/Swiggy), Ride-Hailing (Uber/Ola), and Unknown.
  5. Food/parcel delivery verification via an OCR invoice pipeline (WhatsApp/n8n/FastAPI).
  6. Access Control Engine evaluating entries/exits against configurable policies.
  7. Auditable decision logs with standardized reason codes and confidence scores.
  8. Security guard escalation review queue for low-confidence or anomalous events.
  9. Real-time context and security alerts for physical gate security guards (human-in-the-loop operation).
  10. Security & Admin dashboard (React/Vite).

---

## 2. Host Machine & Hardware Environment

* **Operating System:** Fedora Linux 44 (Workstation Edition)
* **Kernel:** `7.1.13-200.fc44.x86_64` (SMP PREEMPT_DYNAMIC)
* **Architecture:** `x86_64`
* **CPU:** Intel(R) Core(TM) i7-13650HX (14 cores, 20 threads, base 800 MHz, max 4900 MHz)
* **System RAM:** 15 GiB Total (~8 GiB Available, 8 GiB Swap)
* **Disk Space:** NVMe SSD (~81 GiB available, mounted at `/`)
* **Dedicated GPU:** NVIDIA GeForce RTX 4050 Laptop GPU (6141 MiB VRAM), Driver `610.57.04`, CUDA UMD 13.3.
* **Integrated GPU (iGPU):** 13th Gen Intel Iris Xe / UHD Graphics (`/dev/dri/card0`, `/dev/dri/renderD128`).
* **Host Runtimes Installed:**
  * Python `3.14.7` & pip `26.2.1`
  * Node.js `v24.8.0` & npm `11.10.0`
  * Docker Engine `29.7.2` & Docker Compose `5.5.0`
  * Native FFmpeg `8.1.2`
  * Native Tesseract OCR `5.5.3` (Leptonica 1.87.0)
  * Native PostgreSQL client `psql 18.6`
  * Mosquitto client utilities `mosquitto_pub` and `mosquitto_sub`

---

## 3. Critical Architectural Decisions & Gotchas

### ⚠️ A. PostgreSQL Host Port Collision (Port 5433)
* **The Situation:** The host machine already runs a personal PostgreSQL instance natively listening on `127.0.0.1:5432`.
* **The Solution:** The Docker container `campus_postgres` maps **`5433:5432`** on the host.
* **Rule:** NEVER change the host port back to 5432. All connection strings on the host must use `localhost:5433`. Internal container-to-container connections use `postgres:5432`.
* **Credentials:**
  * DB: `campus_security`
  * User: `campus_admin`
  * Password: `campus_dev_pass`
  * Connection URI: `postgresql+psycopg://campus_admin:campus_dev_pass@localhost:5433/campus_security`

### ⚠️ B. Fedora SELinux Bind-Mounts (`:z` flag)
* **The Situation:** Fedora enforces SELinux. Unprivileged container processes (such as Mosquitto user `1883` and Frigate) cannot read/write bind-mounted files labeled `user_home_t` by default.
* **The Solution:** Every volume mount in `docker-compose.yml` must include the `:z` (shared relabeling) flag (e.g. `./config/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro,z`).
* **Frigate Config:** Frigate 0.18 performs automated migrations on `/config/config.yml` at boot; therefore, the mount MUST be read-write with `:z` (`./config/frigate/config.yml:/config/config.yml:z`), NOT `:ro`.

### ⚠️ C. Frigate Hardware Acceleration & Video Encoding
* **The Situation:** Frigate 0.18 auto-detects hardware acceleration. If a non-H.264 video (like generic `mp4v` codec) is fed, VAAPI fails.
* **The Solution:**
  1. The Intel iGPU device node `/dev/dri:/dev/dri` is mounted into `campus_frigate`.
  2. Frigate uses VAAPI hardware decoding on `/dev/dri/renderD128` at negligible CPU and 0.74% iGPU load.
  3. All test video feeds MUST be encoded in standard **H.264 / AVC1** (`libx264`, `yuv420p`).

### ⚠️ D. Python 3.14 & OCR Engine Compatibility
* **The Situation:** Upstream `paddlepaddle` does not currently distribute pre-compiled wheels for Python 3.14.
* **The Solution:** We implemented a robust **dual-engine OCR architecture**:
  1. **RapidOCR (`rapidocr-onnxruntime 1.2.3`):** Uses ONNX Runtime with the exact same PaddleOCR PP-OCRv4 detection and recognition models. Fully functional on Python 3.14.
  2. **Pytesseract (`pytesseract 0.3.13`):** Interfaces with the native host `tesseract 5.5.3` binary.
  Both engines are installed in `.venv` and tested with 100% extraction accuracy on synthetic invoices.

### ⚠️ E. Docker Sandbox Networking & Tool Usage
* The command execution sandbox does not have host network access when `BypassSandbox: false`.
* Whenever a command interacts with host TCP ports (`localhost:5433`, `localhost:1883`, `localhost:5000`, `localhost:5678`) or downloads from PyPI, set `BypassSandbox: true`.
* Always invoke the virtual environment python explicitly: `.venv/bin/python`.

### ⚠️ F. Alembic Migration Candidate Review & PostgreSQL Enums
* Alembic `--autogenerate` generates **candidate** migrations that require human/agent verification.
* Alembic does NOT automatically emit `sa.Enum.create()` when adding new PostgreSQL enum types to existing databases in subsequent migrations. You must explicitly add `sa.Enum(..., name='...').create(op.get_bind(), checkfirst=True)` in `upgrade()` and `drop(op.get_bind(), checkfirst=True)` in `downgrade()`.

### ⚠️ G. Mandatory Schema Drift Detection (`alembic check`)
* Always run `.venv/bin/alembic check` after any modification to models in `backend/app/models/`.
* If `alembic check` reports any operations or non-zero exit, the live database schema and `Base.metadata` have drifted. Drift must be resolved before proceeding.

### ⚠️ H. Authentication, Secrets & Roles (Phase 5C)
* Bearer tokens are HMAC-SHA256 signed with `AUTH_SECRET_KEY` from `.env` (stdlib only, no JWT dependency). If the key is unset the backend uses a random per-process key and logs a warning; every token then dies on restart.
* Passwords are stored as `scrypt$n$r$p$salt$hash` in `users.hashed_password`. Create accounts with `scripts/create_user.py` (password prompted or read from `USER_PASSWORD`).
* Roles are read from the database on every request (`backend/app/dependencies.py`), never trusted from the token. `get_current_user` uses its own short-lived session so the SSE stream never pins a pooled connection.
* `POST /vehicles` requires an authenticated user; `PUT`/`DELETE /vehicles/{plate}` require ADMIN. Clients that called these anonymously (pre-5C) must now send `Authorization: Bearer <token>`.

### ⚠️ I. Live Feed Cursor Ordering (Phase 5C)
* `observation_feed_events.id` is the feed cursor. Every insert takes `pg_advisory_xact_lock(5031602)` first (`services/feed_events.py`), so ids become visible in commit order and `id > since_id` polling can never skip a late-committing row. Always write feed events through `record_feed_event()`, never with a bare `db.add()`.

---

## 4. Repository Directory Layout

```
/home/kirat/coding/honours/
├── .env                        # Local development environment variables (Active)
├── .env.example                # Template for environment configuration
├── .gitignore                  # Git ignore rules
├── alembic.ini                 # Alembic migration configuration
├── context.md                  # THIS FILE (Comprehensive developer/LLM guide)
├── docker-compose.yml          # Services: mosquitto, postgres, frigate, n8n
├── PROJECT_ARCHITECTURE.md     # Research Architecture, Invariants & Topology Specification
├── README.md                   # Project overview, quick start, and test suite commands
├── SETUP_REPORT.md             # Complete environment verification & Phases 1-3 report
│
├── .venv/                      # Python 3.14 virtual environment
│
├── alembic/                    # Database migrations
│   ├── env.py                  # Configured with Base.metadata & DATABASE_URL
│   ├── script.py.mako          # Migration template
│   └── versions/               # Applied migration scripts
│       ├── 3e3fa78436be_create_initial_campus_security_schema.py
│       ├── 9e13fe119fc4_add_vehicle_identity_context.py
│       └── 1c9f9a684531_add_observation_events_and_gate_status.py
│
├── backend/
│   ├── requirements.txt        # Pinned Python package dependencies
│   └── app/
│       ├── __init__.py
│       ├── config.py           # Application settings loaded from .env
│       ├── db.py               # SQLAlchemy engine, SessionLocal, health check
│       ├── mqtt.py             # Paho MQTT manager (listen/pub/health probe)
│       ├── main.py             # FastAPI entrypoint (/health, /vehicles, /gates, /observations, /auth, /owners, /feed, /resolutions)
│       ├── dependencies.py     # get_db, get_current_user (bearer auth), require_roles / require_staff / require_admin
│       ├── models/             # SQLAlchemy 2.0 ORM Entity Models
│       │   ├── __init__.py     # Unified export of all models + enums
│       │   ├── base.py         # Declarative Base & UTC TimestampMixin
│       │   ├── enums.py        # VehicleCategory, PersonType, ResidenceType, GateStatus, ObservationSource, etc.
│       │   ├── identity.py     # User, VehicleOwner (with institutional & residence context), Visitor
│       │   ├── vehicle.py      # Vehicle (raw & normalized plate), DeliveryVehicle
│       │   ├── gate.py         # Gate, AccessDecision, EntryExitLog, SecurityAlert
│       │   ├── delivery.py     # DeliveryOrder, Invoice, InvoiceItem
│       │   ├── health.py       # HealthCheckRecord (continuous heartbeat model)
│       │   ├── observation.py  # ObservationEvent, ObservationResolution (append-only), ObservationFeedEvent (feed cursor log)
│       │   └── movement.py     # CameraLane (declared lane roles), VehicleLinkEvent (append-only)
│       ├── schemas/            # Pydantic validation schemas
│       │   ├── __init__.py
│       │   ├── vehicle.py      # VehicleCreate, VehicleUpdate, VehicleDetailResponse, ResidenceContext
│       │   ├── gate.py         # GateCreate, GateUpdate, GateResponse
│       │   ├── observation.py   # ObservationCreate, ObservationResponse
│       │   ├── feed.py          # ResolvedObservation, FeedPage, ManualObservationCreate, ResolutionCreate
│       │   ├── owner.py         # OwnerCreate
│       │   └── movement.py      # Lanes, movement log, presence, history, vehicle link schemas
│       ├── services/           # Reusable domain services
│       │   ├── __init__.py
│       │   ├── plate_normalizer.py       # normalize_plate, format_plate_display
│       │   ├── vehicle_identity_service.py # Authoritative vehicle & identity resolution service
│       │   ├── observation_service.py    # Ingestion, deduplication, and observation queries
│       │   ├── frigate_event_parser.py   # Frigate MQTT payload parser & camera->gate mapper
│       │   ├── auth_service.py           # scrypt password hashing, signed bearer tokens
│       │   ├── plate_similarity.py       # OCR-aware weighted Levenshtein (ported from Phase 5A)
│       │   ├── identity_resolution_service.py # Observation -> registry linkage view (link_status, suggestions), guard resolutions
│       │   ├── feed_events.py            # record_feed_event / record_registry_update (cursor-ordered change log)
│       │   ├── feed_service.py           # Feed snapshot & changes_since(cursor)
│       │   ├── direction_resolver.py     # Direction from declared lane role / zone order / guard only
│       │   ├── movement_lookup.py        # Movement chains (root + corrections), effective row
│       │   ├── movement_service.py       # Movement write path (on_observation, confirm, correct) + presence/logs/history reads
│       │   ├── vehicle_registration_service.py # Shared POST /vehicles policy + create_vehicle
│       │   └── vehicle_link_service.py   # POST /vehicles/{plate}/link (owner + vehicle + link event)
│       ├── workers/            # Background asynchronous workers
│       │   ├── __init__.py
│       │   └── frigate_mqtt_worker.py    # Persistent MQTT subscriber for frigate/events
│       ├── routes/             # API route controllers
│       │   ├── __init__.py
│       │   ├── vehicles.py     # CRUD + identity context endpoints (/vehicles)
│       │   ├── gates.py        # Gate configuration & observation listing (/gates)
│       │   ├── observations.py # Sensor telemetry ingestion & query (/observations, /observations/manual)
│       │   ├── auth.py         # /auth/login, /auth/me
│       │   ├── owners.py       # GET /owners?q=, POST /owners (ADMIN)
│       │   ├── feed.py         # GET /feed, GET /feed/stream (SSE), GET /feed/snapshots/{id}
│       │   ├── resolutions.py  # POST /resolutions (append-only guard confirmation)
│       │   ├── lanes.py        # GET /lanes, PUT /lanes/{camera_id} (ADMIN)
│       │   ├── movements.py    # GET /logs, GET /logs/{id}, POST /logs/confirm, POST /logs/{id}/corrections
│       │   └── presence.py     # GET /presence, GET /presence/inside
│       └── whatsapp/           # WhatsApp abstraction layer
│           ├── __init__.py
│           ├── base.py         # Abstract WhatsAppProvider interface
│           └── mock.py         # MockWhatsAppProvider for offline dev
│
├── frontend/                   # Guard dashboard (React 19 + Vite 6 + Tailwind 3 + TS); dev server proxies /api -> :8000
│   └── src/                    # api/ (client, types), auth/, feed/ (SSE parser, useLiveFeed), components/
│
├── config/
│   ├── frigate/
│   │   └── config.yml          # Frigate NVR configuration (LPR enabled, gate_cam)
│   └── mosquitto/
│       └── mosquitto.conf      # Mosquitto listener configuration (1883, anon)
│
├── media/                      # Test media files
│   ├── test_invoice.png        # Synthetic delivery invoice image (#ORD-2026-9821)
│   ├── test_plate.png          # High-contrast Indian plate (DL 01 AB 1234)
│   └── test_car_video.mp4      # Looping H.264 video for Frigate camera feed
│
├── n8n/
│   └── workflows/
│       └── test_webhook.json   # Verified n8n test webhook workflow
│
└── scripts/                    # Automated testing and utility scripts
    ├── generate_test_media.py  # Regenerates test invoice, plate, and video
    ├── test_ocr.py             # Standalone OCR validation script
    ├── test_fastapi.py         # Tests /health, /health/db, /health/mqtt
    ├── test_frigate_mqtt.py    # Verifies Frigate telemetry publishing on MQTT
    ├── test_e2e.py             # Full 3-pipeline end-to-end integration test
    ├── test_phase1_models.py   # Comprehensive CRUD & relationship test for models
    ├── test_phase2_vehicle_api.py # 15-scenario test suite for Vehicle Registry & Identity API
    ├── test_phase3_gate_observations.py # 20-scenario test suite for Gate Registry & Observations API
    ├── test_phase4_frigate_mqtt_worker.py # 20-scenario test suite for Frigate MQTT Ingestion Worker
    ├── test_phase5c_live_feed.py # 16-scenario test suite for live feed, linkage, manual entry & permissions
    ├── test_phase6_movement.py # 14-scenario test suite for direction provenance, movement log, presence & linking
    └── create_user.py          # Create/update ADMIN, SUPERVISOR or GUARD accounts
```

---

## 5. Active Services, Ports & Containers

| Service | Container Name | Host Port | Internal Port | URL / Health Endpoint | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Mosquitto MQTT** | `campus_mosquitto` | `1883` | `1883` | `mqtt://localhost:1883` | Anonymous access enabled |
| **PostgreSQL 16** | `campus_postgres` | `5433` | `5432` | `localhost:5433` | DB: `campus_security`, User: `campus_admin` |
| **Frigate NVR** | `campus_frigate` | `5000`, `8554`| `5000`, `8554`| `http://localhost:5000/api/version` | LPR active, VAAPI iGPU decoding |
| **n8n Automation** | `campus_n8n` | `5678` | `5678` | `http://localhost:5678/webhook/test-invoice` | Webhook workflow published |
| **FastAPI Backend** | Host process | `8000` | `8000` | `http://localhost:8000/health` | Run via Uvicorn in `.venv` |

### Managing Services
```bash
# Start all containers
docker compose up -d

# Check running status
docker ps

# Inspect container logs
docker logs --tail 50 campus_frigate
docker logs --tail 50 campus_mosquitto
docker logs --tail 50 campus_postgres
docker logs --tail 50 campus_n8n
```

---

## 6. Database Models & Schema (Phases 1, 2 & 3 Completed)

The PostgreSQL schema is completely implemented in SQLAlchemy 2.0 ORM and managed via Alembic (`alembic upgrade head`).

### Applied Migrations:
1. `3e3fa78436be_create_initial_campus_security_schema.py`: Initial 13 relational tables and enums.
2. `9e13fe119fc4_add_vehicle_identity_context.py`: Added `person_type_enum`, `residence_type_enum`, and extended `vehicle_owners` with institutional identity and residence context.
3. `1c9f9a684531_add_observation_events_and_gate_status.py`: Added `'INACTIVE'` to `gate_status_enum`, created `observation_source_enum`, `observed_vehicle_type_enum`, `observation_direction_enum`, and table `observation_events`.
4. `d529411fb6a3_add_manual_observations_guard_resolutions_and_feed.py` (Phase 5C): idempotent `ADD VALUE IF NOT EXISTS 'MANUAL'` on `observation_source_enum` (it already existed), `created_by_id` on `observation_events`/`vehicles`/`vehicle_owners`, `observation_events.note`, enums `resolution_outcome_enum` and `feed_event_kind_enum` (created explicitly), tables `observation_resolutions` (with an UPDATE/DELETE-rejecting trigger) and `observation_feed_events`.
5. `0453af6c03f6_add_movement_logging_lanes_and_link_events.py` (Phase 6): enums `lane_role_enum`, `direction_method_enum`, `log_plate_source_enum`, `link_method_enum` (explicit), `'MOVEMENT_UPDATED'` added to `feed_event_kind_enum`; table `camera_lanes`; table `vehicle_link_events` (append-only trigger); `entry_exit_logs` gains `observation_id` (unique, root rows), `correction_of_id`, `direction_method`, `direction_confidence`, `direction_evidence`, `plate_source`, `created_by_id`, `note`, and `plate`/`normalized_plate`/`confidence`/`decision`/`reason_code` become nullable; trigger `entry_exit_logs_movement_append_only` rejects UPDATE/DELETE of movement rows (`direction_method IS NOT NULL`; legacy rows unaffected). Downgrade discards Phase 6 movement rows.

### Entities:
1. **`User`** (`users`): System accounts (role: `ADMIN`, `GUARD`, `SUPERVISOR`).
2. **`VehicleOwner`** (`vehicle_owners`): Affiliated campus persons with institutional persona and residence context:
   * `identifier` (e.g. `STUDENT-2026-xxx`, `FACULTY-xxx`)
   * `person_type` (`STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`)
   * `residence_type` (`HOSTELLER`, `DAY_SCHOLAR`, `OFF_CAMPUS`, `UNKNOWN`)
   * `residence` (Hostel block & room, or off-campus address)
   * `department` (Academic/administrative department)
   * `full_name`, `email`, `phone`
3. **`Visitor`** (`visitors`): Guests with validity time windows (`valid_from`, `valid_until`), destination host, and allowed gate.
4. **`Vehicle`** (`vehicles`):
   * `raw_plate` (e.g. `PB65 AB 1234`)
   * `normalized_plate` (e.g. `PB65AB1234`, **Unique Indexed**)
   * `vehicle_category` (`STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`, `VISITOR`, `DELIVERY`, `RIDE_HAILING`, `UNKNOWN`)
   * `status` (`ACTIVE`, `INACTIVE`, `EXPIRED`, `SUSPENDED`, `BLACKLISTED`)
   * Foreign keys to `VehicleOwner` and `Visitor`.
5. **`DeliveryVehicle`** (`delivery_vehicles`): Fleet profile for delivery riders (`platform`: `ZOMATO`, `SWIGGY`, etc.).
6. **`Gate`** (`gates`): Physical gate entities (`GATE_1`, `GATE_2`, `GATE_3`) linked to Frigate `camera_id` with operational status (`ACTIVE`, `MAINTENANCE`, `LOCKED`, `OFFLINE`, `INACTIVE`).
7. **`ObservationEvent`** (`observation_events`): Raw sensory vehicle detection events (`gate_id`, `camera_id`, `observed_at`, `source`, `source_event_id`, `raw_plate`, `normalized_plate`, `plate_confidence`, `vehicle_type`, `vehicle_confidence`, `direction`, `metadata_payload`).
8. **`AccessDecision`** (`access_decisions`): Auditable evaluation log (`decision`: `ALLOWED`, `DENIED`, `REVIEW`, `EXPIRED`), with `reason_code` and explanation.
9. **`EntryExitLog`** (`entry_exit_logs`): Gate crossing journal with `direction` (`ENTRY`, `EXIT`), `confidence`, and `frigate_event_id`. Phase 6 movement records: root row per observation (`observation_id`) + correction rows (`correction_of_id` → root), `direction_method`/`direction_evidence`, `plate_source` (`OBSERVATION`/`GUARD_CORRECTION`), `created_by_id`; `decision` is always NULL for movement records.
10. **`SecurityAlert`** (`security_alerts`): Escalation tickets for security guards (`severity`, `status`, `assigned_to`, `reviewed_by`).
11. **`DeliveryOrder`** (`delivery_orders`): Orders submitted or verified with customer, restaurant, delivery plate, order status, and gate authorization.
12. **`Invoice`** (`invoices`): OCR processed invoice documents with financial totals, confidence, and raw OCR text.
13. **`InvoiceItem`** (`invoice_items`): Line items extracted from invoices.
14. **`HealthCheckRecord`** (`health_checks`): Continuous database heartbeat table (mapped in `backend/app/models/health.py`).
15. **`ObservationResolution`** (`observation_resolutions`, Phase 5C): Append-only guard confirmation for an observation (`outcome` `VEHICLE_CONFIRMED` + `chosen_vehicle_id`, or `NONE_OF_THESE`), `note`, `created_by_id`. Latest row wins in the view; the observation row is never modified. UPDATE/DELETE blocked by ORM listeners and a DB trigger.
16. **`ObservationFeedEvent`** (`observation_feed_events`, Phase 5C): BIGSERIAL change log (`OBSERVATION_CREATED`, `OBSERVATION_UPDATED`, `RESOLUTION_ADDED`, `REGISTRY_UPDATED`) whose id is the live-feed cursor.
17. **`CameraLane`** (`camera_lanes`, Phase 6): Administrator-declared `lane_role` per camera (`ENTRY_LANE`, `EXIT_LANE`, `BIDIRECTIONAL` + optional `outside_zone`/`inside_zone`), `gate_id`, `is_active` (retire instead of delete). Also maps extra cameras to a gate.
18. **`VehicleLinkEvent`** (`vehicle_link_events`, Phase 6): Append-only human assertion that a vehicle belongs to an owner (`method` `GUARD_VERIFIED_ID`/`ADMIN`, `evidence_note`, `linked_by_id`, `linked_at`, `expires_at`). Not proof of identity; no ID images stored.

---

## 7. How to Run the Verification Test Suite

Every component has a dedicated test script in `scripts/`. Always run them using `.venv/bin/python`:

```bash
# 1. Test standalone OCR (Pytesseract & RapidOCR ONNX models)
.venv/bin/python scripts/test_ocr.py

# 2. Test FastAPI health endpoints (/health, /health/db, /health/mqtt, /health/all)
PYTHONPATH=. .venv/bin/python scripts/test_fastapi.py

# 3. Test Frigate MQTT live telemetry publishing
.venv/bin/python scripts/test_frigate_mqtt.py

# 4. Run end-to-end integration test (All 3 pipelines: Camera->Frigate->MQTT->FastAPI->DB, Invoice->OCR->DB, Webhook->n8n->FastAPI)
PYTHONPATH=. .venv/bin/python scripts/test_e2e.py

# 5. Run Phase 1 Database Models & Alembic Schema Verification (CRUD, constraints, relationships)
PYTHONPATH=. .venv/bin/python scripts/test_phase1_models.py

# 6. Run Phase 2 Vehicle Registry & Identity Association API (15/15 scenarios)
PYTHONPATH=. .venv/bin/python scripts/test_phase2_vehicle_api.py

# 7. Run Phase 3 Gate Registry & Gate Observation Management API (20/20 scenarios)
PYTHONPATH=. .venv/bin/python scripts/test_phase3_gate_observations.py

# 8. Run Phase 4 Frigate MQTT Observation Ingestion Worker (20/20 scenarios + Real MQTT)
PYTHONPATH=. .venv/bin/python scripts/test_phase4_frigate_mqtt_worker.py

# 9. Run Phase 5A Identity Resolution Prototype (27/27)
PYTHONPATH=. .venv/bin/python scripts/test_phase5_identity_resolution_prototype.py

# 10. Run Phase 5C Live Feed, Registry Linkage & Manual Entry (16/16; starts uvicorn on :8000, so stop any running backend first)
PYTHONPATH=. .venv/bin/python scripts/test_phase5c_live_feed.py

# 11. Run Phase 6 Movement Logging, Presence & Linking (14/14; starts uvicorn on :8000)
PYTHONPATH=. .venv/bin/python scripts/test_phase6_movement.py

# 12. Verify Alembic Model/Schema Drift (Must report: "No new upgrade operations detected.")
.venv/bin/alembic check
```

### Running the guard dashboard (Phase 5C)
```bash
PYTHONPATH=. .venv/bin/python scripts/create_user.py --username guard1 --full-name "Gate 1 Guard" --email guard1@campus.edu --role GUARD
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev     # http://localhost:5173 (proxies /api to BACKEND_URL, default :8000)
npm run typecheck && npm run build             # verification
```

---

## 8. Plate Normalization Standard

To ensure lookup integrity:
* License plates in India and international standards contain varying spaces, dashes, or casing (e.g. `PB65 AB 1234`, `pb65-ab-1234`, `PB 65AB 1234`).
* Always normalize to uppercase alphanumeric before querying `normalized_plate`:
  ```python
  import re
  def normalize_plate(raw_plate: str) -> str:
      return re.sub(r"[^A-Za-z0-9]", "", raw_plate).upper()
  ```
* Both `raw_plate` and `normalized_plate` are stored in `Vehicle`, `EntryExitLog`, and `AccessDecision`.

---

## 9. Phase 2: Vehicle Registry & Authoritative Identity Resolution

Phase 2 establishes the central server as the authoritative campus intelligence layer. Gates act purely as distributed observation nodes and contain zero business logic.

### Architectural Principle & Pipeline
Identity resolution follows a strict progressive pipeline:
```
PLATE (LPR / Sensor)
  │
  ▼
VEHICLE (`normalized_plate` lookup, validity window, status check)
  │
  ▼
OWNER (`VehicleOwner` record)
  │
  ▼
INSTITUTIONAL IDENTITY (`PersonType`: STUDENT, FACULTY, STAFF, RESIDENT)
  │
  ▼
RESIDENCE CONTEXT (`ResidenceType`: HOSTELLER, DAY_SCHOLAR, OFF_CAMPUS; `residence`: BH-4, Room 312)
```
* **Key Invariant:** Residence context belongs to the person (`VehicleOwner`), never the physical vehicle.
* **Immutability of License Plates:** In `PUT /vehicles/{plate}`, license plate modification is rejected with HTTP 400. Re-registering requires deactivation of the obsolete registration and issuing a fresh record.
* **Audit Trail Soft-Deactivation:** `DELETE /vehicles/{plate}` sets `status = INACTIVE`. Physical records are never deleted from PostgreSQL, guaranteeing unbroken referential integrity for historical access logs and security audits.

### Core Components
* **`backend/app/services/plate_normalizer.py`:** Alphanumeric cleaning and standard display spacing.
* **`backend/app/services/vehicle_identity_service.py`:** Authoritative domain service offering `resolve()`, `get_owner_for_vehicle()`, `is_vehicle_active()`, and `get_residence_context()`.
* **`backend/app/routes/vehicles.py`:** REST endpoints (`POST /vehicles`, `GET /vehicles`, `GET /vehicles/{plate}`, `PUT /vehicles/{plate}`, `DELETE /vehicles/{plate}`).

### The Ten Core Invariants (See PROJECT_ARCHITECTURE.md)
1. **Gate nodes are not authoritative:** Capture observations; hold zero local business logic or access decision state.
2. **Central server is authoritative:** Sole evaluator of policy, curfew, and global campus state.
3. **Plate ≠ Identity:** License plate is a sensory string token, not an institutional persona.
4. **Vehicle ≠ Person:** Assets are decoupled from humans; multiple vehicles per owner; visitors/fleets supported.
5. **Residence belongs to the person:** Hosteller vs. Day-Scholar lives on `VehicleOwner`, never on `Vehicle`.
6. **Observation ≠ Decision:** Camera detection triggers multi-stage evaluation pipeline; never auto-grants entry.
   * *Phase 6 amendment (direction provenance):* a declared camera lane role (`ENTRY_LANE`/`EXIT_LANE`) or declared zone order is **configuration entered by an administrator, not inference**. Direction comes only from that configuration or a guard's confirmation; it is never derived from a camera or gate name. Otherwise it is `UNKNOWN` and no movement is logged. The raw observation keeps the sensor's value; the derived direction lives on the movement record, which carries no access decision.
7. **Traceable Decisions & Security Actions:** Every security alert, review recommendation, or access evaluation records structured `ReasonCode`, context, and confidence scores.
8. **Permanent Audit Trail:** No physical deletion of operational data (`DELETE` = soft deactivation `status=INACTIVE`). Phase 6 movement records and vehicle link events are append-only (DB triggers); fixes are correction rows.
9. **Separate ML & Policy:** Probabilistic computer vision outputs feeds deterministic rule engines.
10. **Unified Campus State:** Three gates feed one global occupancy graph with cross-gate anomaly detection.

---

## 10. Phase 3: Gate Registry & Gate Observation Management

Phase 3 establishes the distributed observation layer for the campus intelligence architecture.

### Operational Principle: Human-in-the-Loop Security at PEC
* Gates at Punjab Engineering College (PEC) are physically operated by authorized human security guards.
* The software does **NOT** autonomously open, close, deny, or control physical barriers (No GPIO, No `GateController`, No `OPEN_BARRIER` commands).
* The software mandate is strictly:
  $$\mathbf{OBSERVE} \longrightarrow \mathbf{ASSOCIATE} \longrightarrow \mathbf{CONTEXTUALIZE} \longrightarrow \mathbf{RECORD} \longrightarrow \mathbf{ALERT}$$
* Invariant verified: `OBSERVATION ≠ DECISION`. An observation records what the sensor saw (`gate_id`, `camera_id`, `raw_plate`, `plate_confidence`, `vehicle_type`, `direction`). It does not evaluate access or create `AccessDecision` records.

### Separation of Sensor Output from Institutional Identity
* `ObservedVehicleType` (`CAR`, `MOTORCYCLE`, `BUS`, `TRUCK`, `BICYCLE`, `UNKNOWN`) is visual sensor output.
* `VehicleCategory` (`STUDENT`, `FACULTY`, `STAFF`, `DELIVERY`, etc.) is institutional classification.
* These concepts are strictly separated.

### Idempotency & Deduplication
* Frigate NVR sends multiple LPR events for the same tracked vehicle across video frames.
* `source_event_id` acts as an idempotency key. Subsequent updates refine the existing `ObservationEvent` (e.g. updating plate confidence from 0.71 to 0.98) without spawning duplicate database rows.

### Core Endpoints Implemented
* `/gates`: `GET /gates`, `POST /gates`, `GET /gates/{id}`, `PUT /gates/{id}`, `DELETE /gates/{id}` (soft-deactivation `status=INACTIVE`), `GET /gates/{id}/observations`.
* `/observations`: `POST /observations` (controlled ingestion), `GET /observations`, `GET /observations/{id}` (structured sensory response without `decision`, `threat`, or `owner`).
* `/vehicles/{plate}/observations`: Format-tolerant plate observation query.

---

## 11. Phase 4: Frigate MQTT Observation Ingestion Worker

Phase 4 bridges the edge camera perception subsystem (Frigate NVR) to the authoritative central observation repository via Mosquitto MQTT.

### Architecture & Data Flow
```
Frigate NVR (gate_cam, LPR)
       │
       ▼ (MQTT topic: frigate/events)
Mosquitto Broker (localhost:1883)
       │
       ▼
FrigateMQTTWorker (backend/app/workers/frigate_mqtt_worker.py)
       │
       ▼
FrigateEventParser (backend/app/services/frigate_event_parser.py)
       ├─► Camera → Gate Resolution (queries Gate by camera_id; unmapped cameras quarantined/skipped)
       ├─► Vehicle Type Mapping (car/motorcycle/bus/truck -> ObservedVehicleType; unknown -> UNKNOWN)
       ├─► LPR Plate Extraction & Normalization (raw_plate, normalized_plate, score; missing plate handled)
       └─► Direction = UNKNOWN (strictly no assumption of entry or exit)
       │
       ▼
ObservationService (backend/app/services/observation_service.py)
       ├─► Idempotency & Deduplication via source_event_id
       └─► Refines existing ObservationEvent (plate, confidence, update_count)
       │
       ▼
PostgreSQL 16 (observation_events table)
```

### Key Operational Guarantees
1. **Strict Ingestion Mandate:** The worker ONLY ingests and translates sensory observations. It is NOT an access-control engine, does NOT evaluate policy, and creates 0 records in `access_decisions`.
2. **Camera $\rightarrow$ Gate Resolution:** Maps camera IDs (`gate_cam` $\rightarrow$ `GATE_1`, `gate_2_cam` $\rightarrow$ `GATE_2`, `gate_3_cam` $\rightarrow$ `GATE_3`). Unknown/unregistered cameras are safely skipped and logged—never defaulted to `GATE_1`.
3. **Idempotency & Refinement:** Consecutive updates for the same tracked object reuse `source_event_id` to refine optical confidence without creating duplicate database rows.
4. **Resilient Reconnection:** Paho client reconnection handlers recover transparently from MQTT broker drops. Malformed JSON payloads are caught safely without terminating the worker thread.
5. **Human-in-the-Loop:** Gates are operated by human security guards; software maintains zero barrier control or GPIO commands.

---

## 11A. Phase 5C: Live Plate Feed, Registry Linkage & Manual Entry

Phase 5C puts the Phase 5A resolution ideas into the live pipeline as a read-only linkage view for guards, plus manual guard input. It shows context and flags only: it never grants or denies access, creates no `AccessDecision`, and has no barrier or GPIO code.

### Resolved view (`IdentityResolutionService`)
For each observation: `{observation, link_status, link_basis, vehicle?, owner?, residence?, suggestions[], resolution?, flags[]}`.

| `link_status` | Rule |
| :--- | :--- |
| `NO_PLATE` | No plate text read |
| `LOW_CONFIDENCE` | Camera read with `plate_confidence < RESOLUTION_CONFIDENCE_THRESHOLD` (default 0.80) or no score. Scored fuzzy suggestions are returned; none is applied, **even an exact registry match** (rule 5). |
| `LINKED` | Confident exact normalized-plate match and `VehicleIdentityService.is_vehicle_active()` (status ACTIVE and inside validity window) |
| `LINKED_INACTIVE` | Same match but status INACTIVE/EXPIRED/SUSPENDED/BLACKLISTED or outside validity window (`VALIDITY_ENDED` / `VALIDITY_NOT_STARTED` flag) |
| `NOT_LINKED` | Confident read, no registry entry (no suggestions), or a guard recorded "none of these" |

* MANUAL observations are typed by a guard and are never `LOW_CONFIDENCE`.
* The latest guard resolution overrides the automatic linkage (`link_basis = GUARD_CONFIRMED`).
* Registry status is reported verbatim (`vehicle.registry_status`). Nothing is labelled THREAT; BLACKLISTED appears only when an administrator recorded it.
* Resolution never writes Vehicle/VehicleOwner/Visitor rows.

### Live feed
* `GET /feed` = snapshot (latest N + `cursor`); `GET /feed?since_id=` = changes after a cursor (polling fallback, `has_more` paging).
* `GET /feed/stream` = SSE (FastAPI `EventSourceResponse`, 15 s keep-alive pings): `ready` event with the cursor, then `feed` events `{kind, cursor, item}`, SSE `id` = cursor, `Last-Event-ID` honoured on reconnect.
* Items are keyed by observation id. Frigate refinements of a `source_event_id` update the same row (Phase 3 idempotency), so clients replace the existing item.
* Registry changes (`POST/PUT/DELETE /vehicles`) re-emit observations of that plate from the last `FEED_REGISTRY_LOOKBACK_HOURS`.

### Manual endpoints (authenticated GUARD/SUPERVISOR/ADMIN)
* `POST /observations/manual`: new `source=MANUAL` row with `created_by_id`, guard-chosen `direction`, `note`; no camera, no confidence, no `source_event_id`. Camera rows are never edited. Generic `POST /observations` rejects `source=MANUAL` (400).
* `POST /resolutions`: append-only `ObservationResolution` (`chosen_vehicle_id` or `"none"`).
* `GET /owners?q=` (staff) / `POST /owners` (ADMIN, 409 on duplicate identifier).
* `POST /vehicles`: ADMIN may register any category. GUARD/SUPERVISOR may register only `VISITOR`/`DELIVERY` with `valid_until` in the future and a window ≤ `GUARD_REGISTRATION_MAX_VALIDITY_HOURS` (default 168). 409 on duplicate plate. `created_by_id` stored.

---

## 11B. Phase 6: Entry/Exit Movement Logging, Presence & Owner Linking

Builds on the 5C resolved-observation service, manual endpoints and SSE. Human-in-the-loop throughout: no barrier/GPIO logic, no `AccessDecision` rows, nothing labelled threat or violation.

### Direction (`DirectionResolver`)
Returns `{direction ENTRY|EXIT|UNKNOWN, method CAMERA_ROLE|ZONE_ORDER|GUARD_CONFIRMED|NONE, confidence, evidence}` from **declared configuration only** (see invariant 6 amendment):

| Source | Result |
| :--- | :--- |
| MANUAL observation with guard-chosen ENTRY/EXIT | `GUARD_CONFIRMED` |
| Camera with active lane `ENTRY_LANE` / `EXIT_LANE` | `CAMERA_ROLE` |
| `BIDIRECTIONAL` lane with `outside_zone` + `inside_zone`, both present in Frigate `entered_zones` | `ZONE_ORDER` (outside→inside = ENTRY, inside→outside = EXIT) |
| No lane, zone-less bidirectional lane, single zone, lane for another gate | `UNKNOWN` / `NONE` with `evidence.reason` |

* Lanes are declared with `PUT /lanes/{camera_id}` (ADMIN). A lane also maps an additional camera to its gate (`FrigateEventParser.resolve_camera_to_gate` falls back to active lanes).
* **No lane is configured for the real `gate_cam`**: its role at PEC is unknown, so its sightings stay UNKNOWN until an administrator declares it.
* `config/frigate/config.yml` was **not** changed. Zone-order direction needs real zone polygons drawn on PEC camera frames; example once coordinates exist:
  ```yaml
  cameras:
    gate_cam:
      zones:
        road_side:   { coordinates: "x1,y1,x2,y2,...", objects: [car, motorcycle, bus, truck] }
        campus_side: { coordinates: "...",             objects: [car, motorcycle, bus, truck] }
  ```
  then `PUT /lanes/gate_cam {"gate_id": "GATE_1", "lane_role": "BIDIRECTIONAL", "outside_zone": "road_side", "inside_zone": "campus_side"}`.

### Movement log (`entry_exit_logs`, `MovementService`)
* Evaluated inside the ingestion transaction (`ObservationService` → `movement_service.on_observation`). A root row is created only for ENTRY/EXIT; UNKNOWN creates none. The feed card then offers **Confirm entry / Confirm exit** (`POST /logs/confirm` → `GUARD_CONFIRMED` root referencing the observation; observation unchanged; 409 if a movement already exists).
* One root per observation (unique `observation_id`, so one per `source_event_id`). Automatic (camera/zone) movements are debounced: same plate + gate + direction within `MOVEMENT_DEBOUNCE_SECONDS` (default 60 s, unverified) of an existing movement → not logged (feed shows `REPEAT_NOT_LOGGED`). Plate-less detections are never debounced; guard actions are never debounced.
* No plate read → movement with plate NULL (`NO_PLATE` flag); a guard-supplied plate is a correction row (`plate_source = GUARD_CORRECTION`).
* Corrections (`POST /logs/{id}/corrections`, direction and/or plate, reason required) append a row whose `correction_of_id` is always the root. The effective view = latest row. When the camera refines the plate of a logged observation a system correction is appended, unless a guard already corrected the plate (human wins).
* Owner attribution is computed on read: observation-sourced plates go through the 5C `IdentityResolutionService` (confidence threshold, guard resolutions, exact registry match), so later registrations and links apply retroactively. Guard-corrected plates use an exact registry match. `vehicle_id` on a row is only the attribution at write time.

### Presence (derived on read)
* `GET /presence`: per vehicle/plate `INSIDE` (latest effective movement ENTRY), `OUTSIDE` (EXIT), `UNKNOWN` (registered vehicle, no movement). `GET /presence/inside`: inside list (linked + unlinked) plus recent plate-less entries.
* Neutral flags on read: `EXIT_WITHOUT_ENTRY`, `ENTRY_WHILE_INSIDE`, `LONG_STAY` (`PRESENCE_LONG_STAY_HOURS`, default 24, unverified), plus `NO_PLATE`, `LOW_CONFIDENCE_PLATE`, `CORRECTED` on movements.
* `GET /logs` (plate, gate, direction, date range, linked, skip/limit) and `GET /vehicles/{plate}/history` (movements + unlogged sightings across all gates in one timeline, presence, link events).
* Reads currently recompute over all movement records per request; fine for development volumes, needs SQL-side aggregation before production scale.

### Linking unknown vehicles (`POST /vehicles/{plate}/link`)
* Body: `owner_id` **or** `new_owner` {person_type, identifier, full_name, residence_type, residence, department?}, `vehicle_category`, validity window, `evidence_note` (required). Minimal PII; no ID images.
* Reuses `create_vehicle` (same policy as `POST /vehicles`: ADMIN for permanent categories; GUARD/SUPERVISOR only VISITOR/DELIVERY with an expiry ≤ `GUARD_REGISTRATION_MAX_VALIDITY_HOURS`; 409 on duplicate plate; 409 on an existing owner identifier for `new_owner`).
* Writes an append-only `VehicleLinkEvent` (`GUARD_VERIFIED_ID` or `ADMIN`). No historical row is rewritten; the response reports how many past movements/sightings now resolve to the owner.

---

## 12. Implementation Roadmap

Follow this strictly sequential development order:
* [x] **Milestone 0:** Environment inspection, Docker infrastructure, and stack verification (Phases 1–13 of setup).
* [x] **Phase 1:** Database Models & Alembic Migrations.
* [x] **Phase 2:** Vehicle Registration API (`POST /vehicles`, `GET /vehicles`, `GET /vehicles/{plate}`, `PUT /vehicles/{plate}`, `DELETE /vehicles/{plate}`) + Identity Context.
* [x] **Phase 3:** Gate Registry & Gate Observation Management API (`/gates`, `/observations`, idempotency, schemas).
* [x] **Phase 4:** Frigate MQTT Observation Ingestion Worker (`FrigateMQTTWorker`, `FrigateEventParser`, 20/20 test suite).
* [x] **Phase 5A:** Isolated Identity & Context Resolution Prototype (`scripts/prototypes/phase5_identity_resolution/`, weighted Levenshtein, hierarchical resolver, 27/27 test suite).
* [ ] **Phase 5B:** Real PEC / Frigate Data Evaluation & Metrics Report (`PHASE5_IDENTITY_EVALUATION.md`).
* [x] **Phase 5C:** Live plate feed with registry linkage & manual entry (`IdentityResolutionService`, `/feed` + SSE, `/observations/manual`, `/resolutions`, auth, guard dashboard slice of Phase 16; 16/16 test suite). Done ahead of 5B at the user's direction; 5B (real PEC data evaluation) remains open and should recalibrate `RESOLUTION_CONFIDENCE_THRESHOLD`.
* [x] **Phase 6:** Entry/exit movement logging with direction provenance (`camera_lanes`, `DirectionResolver`), append-only corrections, derived presence (`/presence`, `/presence/inside`), `GET /logs`, `GET /vehicles/{plate}/history`, owner linking (`POST /vehicles/{plate}/link`, `vehicle_link_events`), guard console pages; 14/14 test suite. Direction on real PEC footage is not yet validated.
* [ ] **Phase 7:** Delivery Order Model & Verification State Management.
* [ ] **Phase 8:** Invoice Processing API (`POST /orders/process-invoice`).
* [ ] **Phase 9:** Delivery Order Matching (`DeliveryVerificationService`).
* [ ] **Phase 10:** WhatsApp Integration (Keep `MockWhatsAppProvider` operational).
* [ ] **Phase 11:** Security Review Queue (`GET /security/reviews`, `POST /security/reviews/{id}/approve`, reject).
* [ ] **Phase 12:** Auditability & Reason Codes.
* [ ] **Phase 13:** FastAPI OpenAPI Documentation grouping.
* [ ] **Phase 14:** Automated End-to-End Test Suite across all 13 test scenarios.
* [ ] **Phase 15:** Simulation Mode (`SIMULATION_MODE=true`).
* [ ] **Phase 16:** React Admin Dashboard (guard live-feed slice delivered in 5C, Inside Campus / Movement Log / Vehicle History pages in 6, under `frontend/`).

---

## 13. Inviolable Developer Rules

1. **NEVER start implementing multiple phases at once.** Proceed phase by phase.
2. **NEVER replace Frigate.** Frigate is the ANPR camera management tool and is working with hardware acceleration.
3. **NEVER train custom ML models.** Use the pre-built OCR (RapidOCR / Tesseract) and Frigate LPR.
4. **NEVER put access-control business logic inside MQTT callbacks.** MQTT handlers should only parse events and dispatch to the `AccessControlEngine`.
5. **NEVER assume OCR output is infallible.** Low-confidence results must route to `REVIEW`, never outright rejection without confidence scoring.
6. **NEVER hard-code database credentials or secrets in Python code.** Always use `backend/app/config.py` and `.env`.
7. **NEVER drop or modify host PostgreSQL databases.** Only operate on `campus_security` via port `5433`.
8. **Always verify existing tests pass before concluding any phase.**
9. **Mandatory Schema Drift Verification:** Always run `.venv/bin/alembic check` after any model change. Never commit code or mark a phase as done if `alembic check` reports detected operations.
10. **Preserve System Invariants:** Strictly adhere to the ten research architecture invariants defined in `PROJECT_ARCHITECTURE.md` (Plate ≠ Identity, Vehicle ≠ Person, Central Authoritative Brain, Gate Nodes Non-Authoritative, etc.).
11. **NO Automated Barrier Control / GPIO / GateController:** Gates at PEC are operated by authorized human security guards. The software observes, associates, contextualizes, records, and alerts. Do NOT implement autonomous barrier actuation, GPIO, or open/close barrier commands.
