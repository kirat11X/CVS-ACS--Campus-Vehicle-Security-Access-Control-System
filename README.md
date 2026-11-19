# Campus Vehicle Security & Access-Control System
## Punjab Engineering College (PEC), Chandigarh

> **Academic & Research Scope:** B.Tech Honors Thesis / Applied Distributed Systems  
> **Authoritative Intelligence Layer & Distributed Gate Observation Network**  
> 
> 🤖 **Live Telegram Delivery & Invoice Intake Bot:** [@KritanshCampusbot](https://t.me/KritanshCampusbot) (`https://t.me/KritanshCampusbot`)

---

## 1. Project Overview

The **Campus Vehicle Security & Access-Control System** is an enterprise-grade vehicle security and intelligence platform designed for **Punjab Engineering College (PEC)** across three perimeter gates (`GATE_1`, `GATE_2`, and `GATE_3`).

### ⚠️ Fundamental Operational Grounding: Human-in-the-Loop Security
**This system is NOT an automated barrier-opening or gate-closing mechanism.**

At PEC, physical barriers and campus gates are operated exclusively by authorized human security personnel. The software does **NOT** autonomously actuate barriers, control GPIO pins, open barriers, or issue barrier commands.

The software's mandate is strictly:
$$\mathbf{OBSERVE} \longrightarrow \mathbf{ASSOCIATE} \longrightarrow \mathbf{CONTEXTUALIZE} \longrightarrow \mathbf{RECORD} \longrightarrow \mathbf{ALERT}$$

The central server serves as the authoritative intelligence brain that:
1. Identifies vehicles entering and leaving campus via camera-based License Plate Recognition (LPR).
2. Associatively resolves institutional personas (Student, Faculty, Staff, Resident, Visitor, Delivery, Ride-Hailing).
3. Distinguishes hostellers from day-scholars and retrieves room/residence context.
4. Verifies food and parcel delivery orders (Zomato, Swiggy) via an OCR invoice parsing pipeline.
5. Contextualizes observations in real time on security guard interfaces.
6. Flags verification requirements and anomalies for human guard action.
7. Maintains an immutable, forensic audit trail across all campus entry/exit points.

---

## 2. The 10 Core Research Invariants

Every subsystem and API endpoint preserves the following foundational invariants (see [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md)):

1. **Gate nodes are not authoritative:** Gate cameras capture telemetry; they contain zero business logic and no local decision authority.
2. **Central server is authoritative:** Exactly one single source of truth—the central server backed by PostgreSQL—maintains campus state.
3. **Plate ≠ Identity:** License plate strings are sensory tokens, not institutional entities.
4. **Vehicle ≠ Person:** Physical machines are decoupled from human stakeholders (supports 1-to-many ownership, fleet couriers).
5. **Residence belongs to the person:** Hosteller vs. Day-Scholar lives on `VehicleOwner`, never on the vehicle.
6. **Observation ≠ Decision:** Ingesting a sensor observation records what was seen; it creates zero access decisions.
7. **Traceable Decisions & Security Actions:** All security notices and audit logs link to observations, identity, and active policies.
8. **Historical Events are Never Destroyed:** Hard deletion of operational data is prohibited (`DELETE` = soft-deactivation `status=INACTIVE`).
9. **Separate ML & Policy:** Probabilistic computer vision models produce confidence scores; deterministic services evaluate security policy.
10. **Unified Campus State:** Three perimeter gates feed one global occupancy graph with cross-gate transit tracking.

---

## 3. Technology Stack & Infrastructure

| Layer / Subsystem | Technology | Configuration / Port | Notes |
| :--- | :--- | :--- | :--- |
| **Backend API** | FastAPI 0.115+ (Python 3.14) | Port `8000` | Asynchronous, SQLAlchemy 2.0 ORM, Pydantic v2 |
| **Database** | PostgreSQL 16.15 (Alpine) | Port `5433` (mapped from `5432`) | Port `5433` avoids host port `5432` collision |
| **Schema Migrations** | Alembic 1.14+ | CLI in `.venv` | Strict drift check (`alembic check`) enforced |
| **Message Broker** | Mosquitto MQTT 2.1.2 | Port `1883` | Asynchronous sensor event bus (`frigate/#`) |
| **Computer Vision / LPR** | Frigate NVR 0.18.0 | Port `5000` (Web/API), `8554` (RTSP) | Intel VAAPI iGPU hardware acceleration active |
| **Document OCR** | RapidOCR (PP-OCRv4) + Tesseract 5.5 | Python 3.14 virtualenv | Dual-engine fallback for delivery invoices |
| **Telegram Intake Bot** | `python-telegram-bot` 21+ | Polling / Webhook (`/telegram/webhook`) | Bot handle: [@KritanshCampusbot](https://t.me/KritanshCampusbot) — PEC resident onboarding & invoice intake |
| **CVS-ACS Screener & LLM** | Ollama (`qwen3:4b-instruct-2507-q4_K_M`) + 26,172 deliverables CSV | Local daemon (port `11434`) | Rule 1 (master list) + Rule 2 (Golden Prompt Screener) + zero-VRAM leak (`keep_alive: 0`) |
| **Workflow Automation** | n8n 1.82+ | Port `5678` | External webhook ingestion & WhatsApp routing |
| **Web & Mobile Console** | React 19 + Vite 6 + Tailwind 3; Capacitor 7 (Android / iOS) | Port `5173` (dev), `4173` (preview) | One codebase: website, installable web app and native app ([`frontend/README.md`](frontend/README.md)) |

---

## 4. Quick Start & Setup

### Prerequisites
- Linux (tested on Fedora 44 x86_64, kernel 7.1.13)
- Docker Engine & Docker Compose
- Python 3.14+ with venv
- Intel iGPU (`/dev/dri`) or compatible hardware acceleration device

### 🚀 One-Command Turnkey Startup (Recommended)
Start the entire project stack—Docker infrastructure (PostgreSQL, Mosquitto, Frigate, n8n), database schema migrations, Ollama local LLM runtime, YOLO11n + CRNN model weights, FastAPI backend API, and the React 19 guard console—with a single command:

```bash
./start.sh            # Starts infrastructure, migrations, models, backend & frontend
```

Useful management commands:
```bash
./start.sh status     # Show health and operational status matrix across all ports
./start.sh demo       # Run the interactive video ANPR & delivery invoice OCR pipeline
./start.sh test       # Execute the full automated pytest verification test suite (138+ tests)
./start.sh stop       # Gracefully shut down frontend, backend, and container services
./start.sh -d         # Launch full stack in daemon (background) mode
```

---

### Manual Step-by-Step Setup

### 1. Start Containerized Infrastructure
```bash
# Start PostgreSQL, Mosquitto MQTT, Frigate NVR, and n8n
docker compose up -d

# Verify all containers are healthy
docker compose ps
```

### 2. Environment Configuration
Ensure `.env` exists in the project root:
```ini
DATABASE_URL=postgresql+psycopg://campus_admin:campus_dev_pass@localhost:5433/campus_security
MQTT_BROKER=localhost
MQTT_PORT=1883
FRIGATE_URL=http://localhost:5000
N8N_WEBHOOK_URL=http://localhost:5678/webhook/test-invoice
RAPIDOCR_ENABLED=true
TESSERACT_ENABLED=true
```

### 3. Run Database Migrations
```bash
# Apply migrations to PostgreSQL
.venv/bin/alembic upgrade head

# Verify zero model/schema drift
.venv/bin/alembic check
```

### 4. Start Backend Server
```bash
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. Start the Console (web) or build the Mobile App
```bash
# Create a sign-in (password prompted)
PYTHONPATH=. .venv/bin/python scripts/create_user.py --username guard1 --full-name "Gate 1 Guard" --email guard1@campus.edu --role GUARD

cd frontend && npm install
npm run dev                # http://localhost:5173 (proxies /api to :8000)
npm run android:build      # debug APK: frontend/android/app/build/outputs/apk/debug/app-debug.apk
```
The app has no proxy: on first launch enter the backend address (e.g. `http://192.168.1.20:8000`) on the sign-in screen. Run the backend with `--host 0.0.0.0` so phones on the LAN can reach it.

---

## 4.1. Telegram Intake & CVS-ACS Campus Screener (`@KritanshCampusbot`)

> 🔗 **Telegram Bot Link:** [https://t.me/KritanshCampusbot](https://t.me/KritanshCampusbot) (Handle: `@KritanshCampusbot`)

The system integrates an autonomous, human-in-the-loop Telegram Bot gateway operating as the primary invoice intake and institutional identity verification mechanism for Punjab Engineering College (PEC).

### 1. Interactive PEC Resident Onboarding
When users access the bot via `/start`:
* **Name Prompt:** Requests user's full name with zero pre-filled suggestion buttons.
* **Institutional ID Verification:** Validates Student ID (SID, e.g. `24103999`), Security Guard ID (`GRD-...`), Faculty/Staff ID (`FAC-...`, `STF-...`), or Residence ID without gate pre-fills.
* **PEC Hostels & Campus Venues (8 Options):**
  - **4 Boys' Hostels:** *Shivalik*, *Aravali*, *Kurukshetra*, *Himalaya*
  - **2 Girls' Hostels:** *Kalpana Chawla*, *Vindhya*
  - **Residence Number:** For campus faculty and staff housing
  - **Others:** Free-text location entry (e.g. *NAB / New Academic Block*, specific departmental buildings, or Designated Gates `Gate 1`, `Gate 2`, `Gate 3`)
* **Returning Member Pop-up:** Existing residents are recognized upon opening the bot with a prompt: *"Do you want to edit something?"* presenting interactive inline actions: `[📍 Change Location]`, `[✏️ Edit Profile]`, and `[✅ Keep As Is / Ready]`. All member profiles persist in the PostgreSQL `telegram_users` table.

### 2. CVS-ACS Campus Security Screener
Screens courier deliveries in real time using `cvs_acs_master_20000_deliverables.csv` (26,172 indexed products):
* **Rule 1 (Strict Master List Compliance):** Matches invoice line items against canonical roots and deliverable items (ignoring pack sizes like `[500g]`, `1L`, `Half/Full`), strictly enforcing the catalog's `category`, `verdict` (`ALLOW`, `REVIEW`, `ALERT`), and `risk_tag`.
* **Rule 2 (Golden Prompt LLM Screener):** If unlisted, queries the local mini LLM (`qwen3:4b-instruct-2507-q4_K_M`) via Ollama with strict conservative safety rules (safe food/groceries $\to$ `ALLOW`, weapons/flammables/chemicals/tobacco $\to$ `ALERT`, unknown/OTC $\to$ `REVIEW`).
* **Zero VRAM Footprint:** Enforces `"keep_alive": 0` on inference to immediately evict LLM weights from memory, preserving GPU/RAM for Frigate computer vision.

### 3. Dual-Engine Invoice Extraction Pipeline
* **Digital PDFs:** Extracted via `pdftotext -layout` for 100% artifact-free digital text.
* **Photos & Screenshots (Swiggy, Zomato, Blinkit):** Runs through an OCR $\to$ LLM pickup pipeline that strips platform fee and tax rows (`Item Total`, `Platform fee with GST`, `Packaging`, `Discount Applied`, `Bill Total`), isolating *only* deliverable items.
* **Phantom Rupee Digit Reconciliation:** Automatically reconciles OCR glyph artifacts (`₹` misread as `3`, `7`, `#`, e.g., ₹180 misread as 3180, or ₹850 misread as 7850) with discount-aware bound checks.
* **Merchant & Location Intelligence:** Extracts merchant/restaurant name (*Roll Nation, Theobroma, La Pino'z Pizza, Blinkit, Zepto*) and outlet locality, storing them in PostgreSQL (`delivery_orders` and `access_decisions.context_data`) for campus delivery trends.

---

## 5. Verification Test Suites

Every phase is validated by a dedicated automated test script:

```bash
# Telegram Connector & Onboarding Test Suite (11/11 PASS)
PYTHONPATH=. .venv/bin/pytest backend/tests/test_telegram_connector.py

# Stage 1 Invoice Screening & OCR Tests (6/6 PASS)
PYTHONPATH=. .venv/bin/pytest backend/tests/test_stage1_invoice_screening_and_ocr.py

# Check Telegram Bot Gateway Status
curl -s http://localhost:8000/telegram/status
# Phase 1: Database Models & Relationships (11/11 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase1_models.py

# Phase 2: Vehicle Registry & Identity Association API (15/15 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase2_vehicle_api.py

# Phase 3: Gate Registry & Gate Observation API (20/20 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase3_gate_observations.py

# Phase 4: Frigate MQTT Ingestion Worker (20/20 PASS + Real MQTT Integration)
PYTHONPATH=. .venv/bin/python scripts/test_phase4_frigate_mqtt_worker.py

# Alembic Schema Drift Check (Must output: "No new upgrade operations detected.")
.venv/bin/alembic check

# End-to-End Multi-Pipeline Integration Test (All 3 Pipelines PASS)
PYTHONPATH=. .venv/bin/python scripts/test_e2e.py

# Standalone OCR Extraction (RapidOCR + Pytesseract PASS)
.venv/bin/python scripts/test_ocr.py

# FastAPI Infrastructure Health Checks (/health, /health/db, /health/mqtt PASS)
PYTHONPATH=. .venv/bin/python scripts/test_fastapi.py

# Frigate Live MQTT Telemetry Publishing (PASS)
.venv/bin/python scripts/test_frigate_mqtt.py

# Phase 16: Console API - CORS, dashboard summary, accounts, owner directory/edit, plate search (7/7 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase16_console_api.py

# Phase 7: Delivery screening - policy table, invoice parser + OCR, LAN intake, deliveries API,
# append-only guard decisions, unified alerts, slide-6 registry match, WhatsApp provider (11/11 PASS; starts uvicorn on :8000)
PYTHONPATH=. .venv/bin/python scripts/test_phase7_delivery_screening.py
```

### Mid-term demo data and the LAN invoice intake (Phase 7)
```bash
# Idempotent: creates the demo owners (SID 24103999 student, FAC-CSE-014 faculty, STF-EST-022 staff),
# their vehicles, guard1 / admin if missing, media/demo/invoice_D-20481.png and screens order D-20481
PYTHONPATH=. .venv/bin/python scripts/seed_demo.py

# Serve on the LAN so a phone can open the intake page
PYTHONPATH=. .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
# Rider / guard phone: http://<server LAN IP>:8000/intake  -> order ID + invoice photo/PDF -> chat-style reply
```
The WhatsApp Business API is not available yet, so `WHATSAPP_PROVIDER=local` (default) keeps replies in an outbox (`media/whatsapp_outbox/outbox.jsonl`) and on the intake result page. `mock` and `meta` (Cloud API stub, needs `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_ID`) plug in behind the same interface; `POST /webhooks/whatsapp` accepts forwarded chat messages (e.g. from n8n).

---

## 6. Implementation Status & Phase Matrix

The project has completed its core architecture, database migrations, security hardening, multi-gate observation ingestion, web/mobile console, and initial ML model training. The remaining work focuses on real-world dataset collection, cloud GPU model fine-tuning, and on-site PEC campus calibration.

- [x] **Milestone 0:** Environment inspection, Docker infrastructure, and containerized stack verification.
- [x] **Phase 1:** Database Models & Alembic Migrations (19 relational models / 7 migrations applied, zero schema drift).
- [x] **Phase 2:** Vehicle Registry API (`/vehicles`) & Authoritative Identity Context (15/15 scenarios PASS).
- [x] **Phase 3:** Gate Registry (`/gates`) & Gate Observation Management (`/observations`, 20/20 scenarios PASS).
- [x] **Phase 4:** Frigate MQTT Observation Ingestion Worker (`frigate_worker`, 20/20 scenarios PASS).
- [x] **Phase 5A & 5C:** Identity resolution prototype (27/27) and live plate feed with SSE stream (`/feed`), manual sightings, and guard resolutions (`/resolutions`, 16/16 scenarios PASS).
- [ ] **Phase 5B:** Real PEC gate video data evaluation & `RESOLUTION_CONFIDENCE_THRESHOLD` calibration (awaiting on-site frames).
- [x] **Phase 6:** Entry/exit movement logging with direction provenance (`DirectionResolver`, `camera_lanes`), append-only corrections, derived presence (`/presence`, `/presence/inside`), `GET /logs`, `GET /vehicles/{plate}/history` (14/14 scenarios PASS).
- [x] **Phase 7:** Delivery invoice screening: dual-engine OCR (RapidOCR + Tesseract fallback) $\rightarrow$ line-item extraction $\rightarrow$ arithmetic check $\rightarrow$ deterministic policy table $\rightarrow$ append-only guard decisions (`/deliveries`, `/alerts`); mobile LAN intake page (`/intake`); edit-distance `registry_match` on feed; demo seed (11/11 scenarios PASS).
- [x] **Phase 8:** Invoice Processing API — delivered as `POST /deliveries/process` and `POST /intake/upload` (multimodal VLM fine-tuning queued for AWS EC2).
- [ ] **Phase 9:** Automated Delivery Order Matching (`DeliveryVerificationService` connecting courier invoices to hostel resident room rosters).
- [x] **Phase 10:** Telegram & WhatsApp Integration — live interactive Telegram bot ([@KritanshCampusbot](https://t.me/KritanshCampusbot)) with PEC resident onboarding (8 campus venues), CVS-ACS screener over 26,172 deliverables, photo OCR $\to$ LLM pickup pipeline, phantom Rupee digit reconciliation, and merchant intelligence extraction (11/11 tests PASS); WhatsApp provider abstraction (`local`, `mock`, `meta` stub, `POST /webhooks/whatsapp`) active.
- [ ] **Phase 11:** Multi-gate Security Review Queue (`GET /security/reviews`, `POST /security/reviews/{id}/resolve`).
- [ ] **Phase 12:** Standardized Immutable Audit Reason Codes.
- [x] **Phase 13:** FastAPI OpenAPI Documentation grouping (16 modular routers with OpenAPI tags).
- [ ] **Phase 14:** Automated End-to-End Test Suite across all 13 canonical operational scenarios.
- [ ] **Phase 15:** Simulation Mode (`SIMULATION_MODE=true` gate stream & WhatsApp invoice replay).
- [x] **Phase 16:** Web & mobile guard console (`frontend/` v0.7.0): React 19 + TypeScript + Vite + Tailwind CSS + Capacitor 7 (Android APK build; 16 views, 7/7 API scenarios PASS).

---

## 7. Master Documentation & Research Suite

The complete technical documentation, architecture specifications, quality assurance guides, empirical test reports, and research whitepapers are organized into dedicated repository documents:

### Core System Manuals & Architecture
| Document | Purpose & Key Contents |
| :--- | :--- |
| **[`DOCUMENTATION_OVERVIEW.md`](DOCUMENTATION_OVERVIEW.md)** | **Master Architectural Blueprint**: Ingestion flow, 4 production Mermaid sequence diagrams (sensor intake, review queue, presence/overstay, and delivery screening), and 19-table database ER schema. |
| **[`API_REFERENCE.md`](API_REFERENCE.md)** | **Complete REST API Manual**: OpenAPI reference for all 17 backend routers with RBAC role rules (`ADMIN`, `GUARD`, `PUBLIC`), request schemas, status codes, and response payloads. |
| **[`DEPLOYMENT_AND_TESTING_GUIDE.md`](DEPLOYMENT_AND_TESTING_GUIDE.md)** | **Operations & QA Runbook**: Container setup, Alembic migrations, dataset seeding/purging via `scripts/manage_dataset.py`, and test execution instructions. |
| **[`WHAT_HAS_BEEN_DONE.md`](WHAT_HAS_BEEN_DONE.md)** | **Exhaustive Inventory**: Completed features, statutory institutional IDs, 1.5h unlinked overstay alert rules, 1,000 multi-vendor QR delivery invoices, 690 campus members, and administrative deletion capabilities. |
| **[`WHAT_HAS_TO_BE_DONE.md`](WHAT_HAS_TO_BE_DONE.md)** | **Future Engineering Roadmap**: AWS EC2 GPU fine-tuning, camera mounting geometry at PEC Gates 1–3, barrier controller integration, and TLS hardening. |

### Academic Research & Production Operations
| Document | Purpose & Key Contents |
| :--- | :--- |
| **[`research/SOTA_CAMPUS_ACCESS_CONTROL_RESEARCH.md`](research/SOTA_CAMPUS_ACCESS_CONTROL_RESEARCH.md)** | **Publication-Ready Research Whitepaper (9,158 words)**: SOTA in Indian ANPR, multi-modal Vision-Language Models (VLMs) for cargo screening, Kuhn-Munkres bipartite matching, and privacy-preserving institutional surveillance. |
| **[`research/PRODUCTION_DEPLOYMENT_AND_EC2_MANUAL.md`](research/PRODUCTION_DEPLOYMENT_AND_EC2_MANUAL.md)** | **Cloud GPU & Production Blueprint**: AWS EC2 `g4dn.xlarge` / `g5.xlarge` setup, Spot instance optimization, automated tmux training workflows, Docker multi-stage containers, Nginx reverse proxy, systemd units, and automated DB backup/restore scripts. |

### Specialized Empirical Test & Audit Reports
| Report | Scope & Validation Metrics |
| :--- | :--- |
| **[`research/TEST_REPORT_VIDEO_ANPR.md`](research/TEST_REPORT_VIDEO_ANPR.md)** | Video pipeline evaluation on `gate_demo_1.mp4`, `gate_demo_2.mp4`, `phase5_test_video.mp4`; ONNX inference latency (41.7 ms); statutory rules (100% pass). |
| **[`research/TEST_REPORT_INVOICE_SCREENING.md`](research/TEST_REPORT_INVOICE_SCREENING.md)** | RapidOCR vs Tesseract on 996 multi-vendor invoices (Zomato, Swiggy, Amazon, Uber, Reliance, Blinkit, Zepto); 97.9% Order ID accuracy; 94% QR detection rate; arithmetic checks. |
| **[`research/TEST_REPORT_IDENTITY_MOVEMENT.md`](research/TEST_REPORT_IDENTITY_MOVEMENT.md)** | Statutory ID schema compliance across 690 members; vehicle linkage; presence tracking; detection of 89 unlinked overstay alerts (>1.5h); 40/40 passing unit/integration tests. |
| **[`research/TEST_REPORT_FRONTEND_UI.md`](research/TEST_REPORT_FRONTEND_UI.md)** | Full UI audit of all 15 navigation routes, College Members Directory (`/members`), interactive modals, mobile responsiveness, and zero build errors (`tsc -b && vite build`). |
| **[`research/TEST_REPORT_ML_PIPELINE.md`](research/TEST_REPORT_ML_PIPELINE.md)** | Audit of Track A OCR, Track B Document VLM, Track C LLM policy engine; 181 passed tests, 93% code coverage, 0 bug tester failures. |
| **[`research/TEST_REPORT_EDGE_CASES.md`](research/TEST_REPORT_EDGE_CASES.md)** | Stress and resilience testing: malformed plates, corrupted invoice uploads, 60s debounce, 1.49h vs 1.50h overstay boundary, and database reconnect; 33/33 tests passed. |
| **[`BUG_TESTER.md`](BUG_TESTER.md)** | Quality assurance and bug testing guide with regression tests and Locust load testing profiles. |
| **[`DATASETS_AND_MODELS.md`](DATASETS_AND_MODELS.md)** | Exhaustive data & model catalog: Indian license plate datasets, invoice corpora, and pretrained/fine-tuned checkpoints. |
| **[`ROADMAP.md`](ROADMAP.md)** | Phased production roadmap from prototype to full campus deployment at PEC Gates 1–3. |
| **[`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md)** | Research architecture, theoretical foundations, 10 core invariants, and distributed system design. |
