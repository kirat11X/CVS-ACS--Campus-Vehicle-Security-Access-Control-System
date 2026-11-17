# BUG TESTER & QUALITY ASSURANCE GUIDE
## Campus Vehicle Security & Access-Control System (CVS-ACS)
### Complete Test Plan, Diagnostic Tools, Regression Matrix, E2E Scenarios, Load Testing, and Security Auditing

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Target Deployment Site:** Punjab Engineering College (PEC), Sector 12, Chandigarh (`GATE_1`, `GATE_2`, `GATE_3`)  
**Core Tool:** `research/cvs_acs_bug_tester.py`  
**Regression Harness:** `scripts/test_audit_regressions.py` + `scripts/audit_regressions/` (19 check modules)

---

## 1. Quality Assurance Architecture & Overview

The CVS-ACS testing ecosystem is built on a multi-tiered verification hierarchy designed to guarantee system invariants, prevent security regressions, validate machine learning perception boundaries, and ensure operational stability under peak campus traffic conditions.

```
+-----------------------------------------------------------------------------------------------+
|                                 CVS-ACS TEST & VERIFICATION STACK                             |
+-----------------------------------------------------------------------------------------------+
| Tier 6: Fault Tolerance & Chaos Testing (DB drop, MQTT disconnect, Frigate RTSP stream crash) |
| Tier 5: High-Concurrency Load & Stress Testing (Locust & JMeter: 100 vehicles/min across gates)|
| Tier 4: Security SAST & PII Audits (Bandit, Ruff, Mypy, JWT validation, log leakage checks)   |
| Tier 3: 13 Multi-Persona End-to-End Scenarios (Student, Faculty, Visitor, Delivery, Curfew)  |
| Tier 2: 20+ Security & Adversarial Regressions (scripts/audit_regressions/ checks)            |
| Tier 1: Static Contracts & Environment Bug Tester (research/cvs_acs_bug_tester.py)            |
+-----------------------------------------------------------------------------------------------+
```

---

## 2. Automated Diagnostic Bug Tester (`research/cvs_acs_bug_tester.py`)

The primary diagnostic tool `research/cvs_acs_bug_tester.py` is an automated, dependency-aware static, contract, environment, and live-stack validator.

### 2.1 Invocation Commands & CLI Parameters

```bash
# 1. Run full static, contract, and environment audit from repository root
python3 research/cvs_acs_bug_tester.py --repo-root .

# 2. Run with live stack connectivity checks (DB port 5433, Mosquitto port 1883, FastAPI port 8000)
python3 research/cvs_acs_bug_tester.py --repo-root . --live

# 3. Export structured audit report to JSON for CI/CD integration
python3 research/cvs_acs_bug_tester.py --repo-root . --json-out bug_report.json

# 4. Execute built-in diagnostic self-test
python3 research/cvs_acs_bug_tester.py --self-test
```

### 2.2 Check Taxonomy & Diagnostic Codes

The tester evaluates checks across 8 distinct architectural categories:

| Check ID | Category | Severity | Target Contract & Remediation |
| :--- | :--- | :--- | :--- |
| `REPO-001` | **Repository Structure** | `HIGH` | Validates presence of core anchor files (`README.md`, `backend/app/main.py`, `frontend/src/App.tsx`, `research_track/MANIFEST.yaml`, `scripts/test_audit_regressions.py`). |
| `DOC-001` | **Documentation Drift** | `MEDIUM` | Detects drift between `README.md` roadmap status and actual implemented backend routers/frontend views. |
| `DATA-001` | **Dataset Integrity** | `MEDIUM` | Enforces canonical row counts across item taxonomy datasets (`seed_items.csv` vs `item_taxonomy_seed.csv` = exactly 320 items). |
| `PROD-001` | **Production Readiness** | `HIGH` | Verifies that production entrypoints do not directly leak `mock_whatsapp` or test stubs into default execution paths. |
| `SEC-001` | **Cryptographic Config** | `CRITICAL`| Verifies that `AUTH_SECRET_KEY` is not a placeholder, is at least 32 bytes, and is properly loaded from `.env`. |
| `ML-A-001` | **Track A Perception** | `LOW` | Verifies imports and execution of `normalize_plate()` and `OpticalPlateMatcher` across standard Indian series. |
| `ML-B-001` | **Track B Extraction** | `LOW` | Verifies imports of `InvoiceReconciler`, JSON Schema Draft 2020-12 validator, and Decimal math operations. |
| `ENV-001` | **Python Environment** | `MEDIUM` | Verifies host Python version. Warns on Python 3.14+ for ML packages and points to the isolated Python 3.12 ML venv. |
| `ENV-002` | **Keras/Torch Backend** | `MEDIUM` | Verifies that `KERAS_BACKEND=torch` is explicitly configured to prevent local TensorFlow 2.21 CUDA initialization failures. |
| `ENV-003` | **System Memory Gate** | `HIGH` | Verifies available system RAM ($\ge 6.0\text{ GiB}$) to prevent OOM kills, flagging memory consumers like GNOME `localsearch-3`. |

---

## 3. Adversarial Security Regression Suite (`scripts/audit_regressions/`)

Following the comprehensive adversarial audit of `2026-10-13`, 19 regression modules were developed under `scripts/audit_regressions/` covering **20+ specific security and ingestion vulnerabilities**.

### 3.1 Execution Guide
Regression tests execute in-process using FastAPI's `TestClient` against an isolated scratch PostgreSQL database:

```bash
# Execute entire regression suite
DATABASE_URL=postgresql+psycopg://campus_admin:campus_dev_pass@localhost:5433/campus_scratch \
PYTHONPATH=. .venv/bin/python scripts/test_audit_regressions.py

# Execute specific pattern-matched regression scenario (e.g., truncate protection)
DATABASE_URL=postgresql+psycopg://campus_admin:campus_dev_pass@localhost:5433/campus_scratch \
PYTHONPATH=. .venv/bin/python scripts/test_audit_regressions.py -k truncate
```

### 3.2 Regression Check Catalog & Vulnerability Coverage

```
+------------------------------------+--------------------------------------------------------------------------+
| Check Module                       | Vulnerability / Regression Scenario Covered                              |
+------------------------------------+--------------------------------------------------------------------------+
| check_alembic_percent_url.py       | Verifies '%' characters in DATABASE_URL passwords do not break Alembic. |
| check_append_only_truncate.py      | Verifies DB triggers reject TRUNCATE on append-only audit & log tables.   |
| check_auth_personal_data_reads.py  | Verifies staff bearer JWT is required to read personal owner/visitor data.|
| check_auth_secret_placeholder.py   | Verifies backend refuses to boot if AUTH_SECRET_KEY is a default/weak key.|
| check_auth_unauthenticated_writes  | Verifies unauthenticated POST/PUT/DELETE requests are blocked (HTTP 401).|
| check_bearer_token_non_ascii.py    | Verifies non-ASCII bearer headers return clean 401 instead of 500 crashes.|
| check_debug_mqtt_buffer_privacy.py | Verifies the raw MQTT telemetry debug buffer requires ADMIN privileges.  |
| check_detector_score_not_plate_score| Verifies YOLO box confidence cannot masquerade as plate OCR score.     |
| check_fresh_database_migrations.py | Verifies a fresh database passes 'alembic check' with zero schema drift. |
| check_frigate_018_plate_fields.py  | Verifies correct parsing of Frigate 0.18 recognized_license_plate payload|
| check_gate_camera_ambiguity.py     | Verifies single live gate per camera and deterministic camera resolution. |
| check_health_probe_no_ddl.py       | Verifies /health endpoints execute SELECT 1 without issuing DDL.         |
| check_history_superseded_resolution| Verifies vehicle history view applies latest guard override resolution.  |
| check_nonfinite_confidence.py      | Verifies NaN, +Inf, -Inf in Frigate payloads are rejected as malformed.  |
| check_observation_idempotency_race | Verifies concurrent duplicate event ingestion creates exactly one record.|
| check_orm_movement_guard.py        | Verifies ORM movement listener enforces stored direction_method.         |
| check_overlong_fields.py           | Verifies request length validation matches PostgreSQL VARCHAR limits.    |
| check_person_not_vehicle.py        | Verifies pedestrian/human detections are filtered and not logged as cars.|
| check_plate_text_not_logged.py     | Verifies raw plate text and request bodies are redacted from app logs.   |
+------------------------------------+--------------------------------------------------------------------------+
```

---

## 4. Phase-by-Phase Integration Test Suites

The codebase provides automated test harnesses for all implemented operational phases:

```bash
# Phase 1: Database Models & SQLAlchemy 2.0 Relationships (11/11 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase1_models.py

# Phase 2: Vehicle Registry API & Ownership Linking (15/15 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase2_vehicle_api.py

# Phase 3: Gate Registry & Observation Ingestion API (20/20 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase3_gate_observations.py

# Phase 4: Frigate MQTT Worker & Event Deduplication (20/20 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase4_frigate_mqtt_worker.py

# Phase 5C: Live Plate Feed, SSE Stream & Guard Resolutions (16/16 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase5c_live_feed.py

# Phase 6: Entry/Exit Movement Logging & Direction Resolution (14/14 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase6_movement.py

# Phase 7: Delivery Screening, Invoice OCR & Policy Table (11/11 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase7_delivery_screening.py

# Phase 16: Guard & Admin Console Backend APIs (7/7 PASS)
PYTHONPATH=. .venv/bin/python scripts/test_phase16_console_api.py

# Three-Pipeline End-to-End Multi-Service Integration Test (All PASS)
PYTHONPATH=. .venv/bin/python scripts/test_e2e.py
```

---

## 5. The 13 Multi-Persona End-to-End Test Scenarios

To validate campus operations before live pilot deployment, the system must execute the 13 canonical end-to-end operational scenarios across all institutional personas and vehicle categories:

```
+-------------------------------------------------------------------------------------------------------+
|                                  THE 13 CANONICAL E2E SCENARIOS MATRIX                                |
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| No. | Persona / Test Scenario    | Input Event           | Policy Outcome     | Target System Action  |
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S01 | Resident Student (Hosteller) | Plate read at Gate 2  | ALLOW (24/7 Access)| Display room context; |
|     | Vehicle Entry/Exit         | (Kalam Hall Hosteller)|                    | Log entry_exit_log.   |
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S02 | Day-Scholar Student Normal | Plate read at Gate 1  | ALLOW (Daytime)    | Record daytime entry; |
|     | Daytime Entry              | (14:15 weekday)       |                    | update presence=INSIDE|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S03 | Day-Scholar Student Curfew | Plate read at Gate 1  | REVIEW             | Visual flag on console|
|     | Violation (Late Night)     | (23:45 night)         | Reason: CURFEW_FLAG| Guard must confirm ID.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S04 | Faculty / Staff Member     | Plate read at Gate 3  | ALLOW (Unrestricted| Display Department    |
|     | Standard Transit           | (CSE Faculty Car)     | 24/7 Access)       | (e.g. CSE Dept).      |
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S05 | Registered Official Visitor| Plate read at Gate 1  | ALLOW (In Window)  | Show Host / Dept name;|
|     | (Within Valid Window)      | (Active Visitor Pass) |                    | countdown valid hours.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S06 | Expired / Unregistered     | Plate read at Gate 1  | REVIEW             | Prompt guard for 1-clk|
|     | Visitor Vehicle            | (No active pass)      | Reason: UNREGISTERED temporary visitor pass.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S07 | Permissible Food Delivery  | Zomato courier with   | ALLOW              | Parse items; verify   |
|     | (Meals / Groceries)        | Burger + Coke invoice | Reason: FOOD_OK    | arithmetic; 1-clk clear
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S08 | Ambiguous Delivery Invoice | Swiggy courier with   | REVIEW             | Highlight unclear line|
|     | (Unread items / Bad Math)  | torn receipt (CER>15%)| Reason: ARITH_FAIL | Guard manually checks.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S09 | Contraband Delivery Alert  | Delivery with alcohol,| ALERT (Contraband) | Loud audio alert; red |
|     | (Tobacco / Alcohol / Vape) | vapes, or knives      | Reason: TOBACCO_RES| banner; notify warden.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S10 | Ride-Hailing Cab Transit   | Uber entering Gate 1, | ALLOW (Transit     | Track cross-gate time;|
|     | (Drop-off & Fast Exit)     | exiting Gate 2 (<15m) | Window Active)     | mark presence=OUTSIDE.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S11 | Tailgating / Directional   | 2 vehicles close;     | REVIEW             | Create separate provi-|
|     | Anomaly at Lane Sensor     | camera reads 1 plate  | Reason: LANE_ANOMAL| sional rows for guard.|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S12 | Degraded Sensor Fallback   | Camera stream drops;  | FALLBACK (Manual)  | Fast manual search bar|
|     | (Camera / Network Offline) | guard enters plate    | Reason: MANUAL_READ| Guard records sighting|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
| S13 | Authoritative Guard        | Model misreads plate; | GUARD OVERRIDE     | Save guard resolution;|
|     | Resolution Override        | guard enters true text| (Authoritative Win)| model audit trail kept|
+-----+----------------------------+-----------------------+--------------------+-----------------------+
```

---

## 6. High-Concurrency Load & Stress Testing Specification

To certify CVS-ACS for deployment during campus peak rush hours (convocation, morning arrival, fest events), the system must be benchmarked under simulated peak loads using **Locust** and **Apache JMeter**.

### 6.1 Performance Target & Service Level Objectives (SLOs)
- **Target Ingestion Throughput:** **100 vehicle arrivals per minute** distributed across PEC Gate 1 (50%), Gate 2 (30%), and Gate 3 (20%).
- **Peak Burst Ingestion:** 5 concurrent vehicle arrivals in a 3-second window at Gate 1.
- **API Latency SLO:**
  - $p_{50} \le 120\text{ ms}$ for plate ingestion (`POST /observations`).
  - $p_{95} \le 450\text{ ms}$ for live dashboard summary (`GET /dashboard/summary`).
  - $p_{99} \le 2000\text{ ms}$ during concurrent OCR processing.
- **Reliability:** Zero unhandled HTTP 500 crashes; zero message drops on Mosquitto MQTT.

### 6.2 Locust Stress Testing Script (`scripts/load_test_locust.py`)

```python
import json
import random
import time
from locust import HttpUser, task, between

SAMPLE_PLATES = [
    "CH01AB1234", "HR26DK0042", "PB65XY7788", "DL01AB9999", 
    "UP32KL5567", "CH04MN3090", "PB02BV1122", "HR05EF4455"
]

GATES = ["GATE_1", "GATE_2", "GATE_3"]

class CampusGateUser(HttpUser):
    wait_time = between(0.5, 1.5)

    def on_start(self):
        """Obtain staff bearer token."""
        resp = self.client.post("/auth/login", data={"username": "guard1", "password": "Guard@12345"})
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @task(5)
    def simulate_plate_observation(self):
        """Simulate high-frequency plate observation."""
        plate = random.choice(SAMPLE_PLATES)
        gate = random.choice(GATES)
        payload = {
            "gate_id": gate,
            "camera_id": f"{gate.lower()}_cam",
            "source": "FRIGATE_MQTT",
            "source_event_id": f"evt_{int(time.time()*1000)}_{random.randint(100,999)}",
            "raw_plate": plate,
            "plate_confidence": round(random.uniform(0.75, 0.98), 2),
            "vehicle_type": "car",
            "vehicle_confidence": 0.95
        }
        self.client.post("/observations", json=payload, headers=self.headers)

    @task(3)
    def fetch_live_feed_and_dashboard(self):
        """Simulate active guard console polling."""
        self.client.get("/dashboard/summary", headers=self.headers)
        self.client.get("/presence/inside", headers=self.headers)

    @task(1)
    def simulate_invoice_submission(self):
        """Simulate periodic delivery order intake."""
        order_id = f"ORD-{random.randint(10000, 99999)}"
        self.client.post("/intake/upload", data={"order_id": order_id, "vendor": "Zomato"})
```

---

## 7. Security SAST, PII Protection, and Code Quality Audits

The codebase enforces strict static analysis security testing (SAST) and code formatting gates prior to any deployment.

### 7.1 Security & Quality Commands

```bash
# 1. Static Security Analysis (Bandit)
# Scans Python AST for SQL injections, weak cryptography, hardcoded passwords
bandit -r backend/ -ll -x "backend/tests,backend/.venv"

# 2. Strict Python Linting (Ruff)
# Enforces PEP 8, import sorting, security rules, and code quality
ruff check backend/ scripts/ research_track/

# 3. Static Type Analysis (Mypy)
# Enforces strict type hint verification across models, routes, and services
mypy --config-file pyproject.toml backend/app/

# 4. Frontend Type & Build Verification
cd frontend && npm run typecheck && npm run build
```

### 7.2 PII Protection & Data Privacy Audit Protocol
1. **Zero Face Storage:** Frigate filters and application services reject any human facial bounding boxes. CCTV frames containing human faces are blurred or discarded.
2. **Log Redaction:** All application loggers run through a sanitization filter ensuring license plate numbers, phone numbers, and student hostel room numbers are never printed in plaintext to stdout or systemd journals.
3. **Password Security:** All passwords hashed using bcrypt or PBKDF2 with SHA-256 (minimum 100,000 iterations); raw passwords never stored or returned in JSON responses.

---

## 8. Failure Mode & Resilience Testing (Chaos Engineering)

To ensure campus security operations continue uninterrupted during system degradations, the following failure modes are continuously simulated and tested:

```
+-------------------------------------------------------------------------------------------------------+
|                                    CHAOS & RESILIENCE TEST MATRIX                                     |
+-----------------------+-------------------------------+-----------------------+-----------------------+
| Injected Failure      | Chaos Simulation Command      | Expected Behavior     | Recovery Protocol     |
+-----------------------+-------------------------------+-----------------------+-----------------------+
| 1. PostgreSQL Outage  | docker compose stop db        | API returns HTTP 503  | SQLAlchemy pool auto- |
|                       |                               | (Database Offline);   | reconnects on reboot; |
|                       |                               | UI displays warning   | zero data corruption. |
+-----------------------+-------------------------------+-----------------------+-----------------------+
| 2. MQTT Broker Drop   | docker compose stop mosquitto | Frigate worker buffers| Worker reconnects with|
|                       |                               | events locally in RAM;| exponential backoff;  |
|                       |                               | reconnects on restart | processes backlogged. |
+-----------------------+-------------------------------+-----------------------+-----------------------+
| 3. Frigate Camera Down| ifconfig <cam_interface> down | Dashboard displays    | Watchdog alerts guard;|
|                       |                               | "CAMERA OFFLINE" card;| guard switches to     |
|                       |                               | FPS counter drops to 0| manual plate entry.   |
+-----------------------+-------------------------------+-----------------------+-----------------------+
| 4. Corrupt OCR Image  | Feed 0-byte or corrupt JPEG   | RapidOCR logs warning;| Image rejected safely;|
|                       | to /intake/upload             | returns HTTP 422;     | no service crash or   |
|                       |                               | prompt user to re-snap| unhandled 500 error.  |
+-----------------------+-------------------------------+-----------------------+-----------------------+
| 5. Rapid Network Flap | Drop WiFi connection on guard | LiveFeedContext auto- | Console auto-resumes  |
|    on Guard Mobile    | phone for 30 seconds          | switches from SSE to  | SSE stream cursor with|
|                       |                               | cached REST polling   | zero duplicate items. |
+-----------------------+-------------------------------+-----------------------+-----------------------+
```

---

## 9. QA Acceptance Criteria for Production Sign-Off

Before CVS-ACS is cleared for pilot operations at PEC Gate 1, all criteria below must be certified:

- [ ] All 10 anchor checks in `python3 research/cvs_acs_bug_tester.py --repo-root .` report `PASS` (0 Failures, 0 Critical Warnings).
- [ ] All 20+ scenarios in `scripts/test_audit_regressions.py` report `PASS`.
- [ ] `alembic check` returns "No new upgrade operations detected."
- [ ] Pytest coverage in `research_track/review/` exceeds 90%.
- [ ] All 13 canonical E2E operational scenarios pass verification.
- [ ] Locust 100 vehicles/minute stress test completes with $p_{95} \le 450\text{ ms}$ and 0 errors.
- [ ] Bandit, Ruff, and Mypy report zero critical or high severity security/type blockers.
- [ ] Human guard manual override is validated to supersede AI suggestions in 100% of test cases.
