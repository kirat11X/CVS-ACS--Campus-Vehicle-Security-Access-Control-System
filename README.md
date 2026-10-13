# Campus Vehicle Security & Access-Control System
## Punjab Engineering College (PEC), Chandigarh

> **Academic & Research Scope:** B.Tech Honors Thesis / Applied Distributed Systems  
> **Authoritative Intelligence Layer & Distributed Gate Observation Network**

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
| **Workflow Automation** | n8n 1.82+ | Port `5678` | External webhook ingestion & WhatsApp routing |
| **Security Dashboard** | React + Vite + Tailwind CSS | Port `3000` (Phase 16) | Guard contextualization & alert review UI |

---

## 4. Quick Start & Setup

### Prerequisites
- Linux (tested on Fedora 44 x86_64, kernel 7.1.13)
- Docker Engine & Docker Compose
- Python 3.14+ with venv
- Intel iGPU (`/dev/dri`) or compatible hardware acceleration device

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

---

## 5. Verification Test Suites

Every phase is validated by a dedicated automated test script:

```bash
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
```

---

## 6. Implementation Roadmap

- [x] **Milestone 0:** Environment inspection, Docker infrastructure, and stack verification.
- [x] **Phase 1:** Database Models & Alembic Migrations (14 relational tables).
- [x] **Phase 2:** Vehicle Registry API (`/vehicles`) & Authoritative Identity Context.
- [x] **Phase 3:** Gate Registry (`/gates`) & Gate Observation Management (`/observations`).
- [x] **Phase 4:** Frigate MQTT Observation Ingestion Worker.
- [ ] **Phase 5:** Access Control Engine (Policy rules for guard context & alerts).
- [ ] **Phase 6:** Entry / Exit Tracking & History APIs (`GET /logs`, `GET /vehicles/{plate}/history`).
- [ ] **Phase 7:** Delivery Order Model & Verification State Management.
- [ ] **Phase 8:** Invoice Processing API (`POST /orders/process-invoice`).
- [ ] **Phase 9:** Delivery Order Matching (`DeliveryVerificationService`).
- [ ] **Phase 10:** WhatsApp Integration (Abstract provider with offline dev mock).
- [ ] **Phase 11:** Security Review Queue (`/security/reviews`).
- [ ] **Phase 12:** Auditability & Reason Codes.
- [ ] **Phase 13:** FastAPI OpenAPI Documentation grouping.
- [ ] **Phase 14:** Automated End-to-End Test Suite across all 13 test scenarios.
- [ ] **Phase 15:** Simulation Mode (`SIMULATION_MODE=true`).
- [ ] **Phase 16:** React Guard & Admin Dashboard.

---

## 7. Documentation Directory

- [`context.md`](context.md): Comprehensive developer onboarding and LLM context guide.
- [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md): Research architecture, theoretical foundations, and system invariants.
- [`SETUP_REPORT.md`](SETUP_REPORT.md): Complete infrastructure verification and phase execution reports.
