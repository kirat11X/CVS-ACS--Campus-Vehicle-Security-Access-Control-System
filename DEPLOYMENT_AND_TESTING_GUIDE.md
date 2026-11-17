# CVS-ACS Deployment & Operations Manual
## Campus Vehicle Security & Access Control System
### Production Deployment, Infrastructure Setup, Dataset Management & Quality Assurance Guide

**Target Site:** Punjab Engineering College (PEC), Sector 12, Chandigarh  
**Operating Environment:** Linux (Fedora 40/41/44, Ubuntu 22.04/24.04 LTS)  
**Repository Root:** [/home/kirat/coding/honours](file:///home/kirat/coding/honours)  

---

## 1. System Prerequisites & Dependencies

Before deploying the CVS-ACS stack, verify the target host satisfies the minimum hardware and software requirements:

### 1.1 Minimum Hardware Specifications
- **CPU:** 4 physical cores (x86_64 or ARM64)
- **RAM:** 8 GB minimum (16 GB recommended for concurrent video inference)
- **Storage:** 50 GB NVMe / SSD (for PostgreSQL volumes, video clips, and invoice images)
- **GPU (Optional for edge inference):** Intel iGPU with VAAPI support or NVIDIA GPU with CUDA 12.x
- **Network:** 1 Gbps Ethernet connection to perimeter camera VLAN

### 1.2 System Package Installation
Install foundational operating system libraries, OCR binaries, and container runtimes:

#### On Fedora / RHEL / Rocky Linux:
```bash
sudo dnf install -y \
    python3-devel \
    python3-pip \
    nodejs \
    npm \
    docker-ce \
    docker-compose-plugin \
    tesseract \
    tesseract-langpack-eng \
    poppler-utils \
    mesa-dri-drivers \
    libglvnd-glx \
    git
```

#### On Ubuntu / Debian:
```bash
sudo apt update && sudo apt install -y \
    python3-dev \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
    docker.io \
    docker-compose-v2 \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    git
```

Ensure the current user belongs to the `docker` group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

---

## 2. Environment Configuration

Clone the repository and prepare the runtime environment configuration:

```bash
cd /home/kirat/coding/honours
cp .env.example .env
```

Edit `.env` to configure secure deployment secrets:

```ini
# Core Database Settings (Host port 5433 avoids conflict with local PostgreSQL 5432)
DATABASE_URL=postgresql+psycopg://campus_admin:campus_dev_pass@localhost:5433/campus_security
POSTGRES_USER=campus_admin
POSTGRES_PASSWORD=campus_dev_pass
POSTGRES_DB=campus_security
POSTGRES_PORT=5433

# Telemetry Bus (Mosquitto MQTT)
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
MQTT_TOPIC_EVENTS=frigate/events
MQTT_TOPIC_REVIEWS=frigate/reviews

# Authentication & Security
AUTH_SECRET_KEY=94709d0dbcf734f590ff212e132cbe38706fae91c7a3e91d5f20
ACCESS_TOKEN_EXPIRE_MINUTES=1440
AUTH_PASSWORD_MIN_LENGTH=8

# Communications & Intake
WHATSAPP_PROVIDER=local
INTAKE_PUBLIC_URL=http://192.168.1.100:8000/intake
MEDIA_ROOT=media

# Logging & Telemetry
LOG_LEVEL=INFO
```

> [!CAUTION]
> In production environments, generate a 64-character cryptographically random `AUTH_SECRET_KEY`:
> ```bash
> openssl rand -hex 32
> ```
> The application will refuse to start if `AUTH_SECRET_KEY` is left as a placeholder or is shorter than 32 characters.

---

## 3. Containerized Infrastructure Orchestration

The foundational infrastructure runs containerized via `docker-compose.yml`:
- **PostgreSQL 16.15 (Alpine):** Port `5433` (mapped from container `5432`)
- **Mosquitto MQTT 2.1.2:** Port `1883`
- **Frigate NVR 0.18.0:** Web UI Port `5000`, RTSP Port `8554`
- **n8n Workflow Engine:** Port `5678`

### 3.1 Starting Core Infrastructure
```bash
cd /home/kirat/coding/honours
docker compose up -d postgres mosquitto frigate n8n
```

### 3.2 Verifying Container Health
Verify all services are healthy and running:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected output:
```
NAMES               STATUS                    PORTS
campus_postgres     Up 4 hours (healthy)      0.0.0.0:5433->5432/tcp
campus_mosquitto    Up 4 hours (healthy)      0.0.0.0:1883->1883/tcp
campus_frigate      Up 4 hours (healthy)      0.0.0.0:5000->5000/tcp, 0.0.0.0:8554->8554/tcp
campus_n8n          Up 4 hours (healthy)      0.0.0.0:5678->5678/tcp
```

---

## 4. Python Backend Service Setup

### 4.1 Virtual Environment Provisioning
Initialize a Python 3.14 (or Python 3.12) virtual environment and install application dependencies:

```bash
cd /home/kirat/coding/honours
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r backend/requirements.txt
```

### 4.2 Database Migrations via Alembic
Execute version-controlled migrations to construct the 19 relational entities:

```bash
# Execute schema migration head
.venv/bin/alembic upgrade head

# Confirm zero schema drift
.venv/bin/alembic check
```

Expected output:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
No new upgrade operations detected.
```

---

## 5. PostgreSQL Dataset Management & Seeding

The repository provides an authoritative dataset utility ([scripts/manage_dataset.py](file:///home/kirat/coding/honours/scripts/manage_dataset.py)) to seed, inspect, and cleanly purge database records without violating foreign keys or append-only trigger restrictions.

```
+---------------------------------------------------------------------------------------------------+
|                              CVS-ACS DATASET MANAGEMENT UTILITY                                   |
|                              File: scripts/manage_dataset.py                                      |
+--------------------------+------------------------------------------------------------------------+
| Command Flag             | Operational Action                                                     |
+--------------------------+------------------------------------------------------------------------+
| `--status`               | Displays real-time database counts of members, vehicles, movements,    |
|                          | observations, delivery orders, invoices, items, and files on disk.     |
| `--seed`                 | Triggers full synthetic dataset seeding (500 students, 100 faculty,    |
|                          | 50 residents, 20 staff, 500 vehicles, 1,000 multi-vendor QR invoices). |
| `--purge-invoices`       | Purges all delivery orders, invoices, items, and preview files.        |
| `--purge-members`        | Purges generated members, vehicles, links, and movements while         |
|                          | safely preserving core administrative accounts and demo vehicles.      |
| `--purge-all`            | Resets PostgreSQL state completely to bare migration baseline.         |
| `--force`                | Bypasses interactive terminal confirmation prompt.                     |
+--------------------------+------------------------------------------------------------------------+
```

### 5.1 Inspect Current Database Dataset Status
```bash
python3 scripts/manage_dataset.py --status
```

Sample output:
```
=================================================================
CURRENT POSTGRESQL DATASET STATUS
=================================================================
Vehicle Owners (Total: 673):
  • Students:              502
  • Faculty Members:       101
  • Staff / Administration: 20
  • Campus Residents:       50

Vehicles & Movements:
  • Registered Vehicles:   506
  • Vehicle Link Events:   460
  • Gate Movement Logs:    1042
  • Observation Events:    1042

Deliveries & Invoices:
  • Delivery Orders:       1000
  • Invoices in DB:        1000
  • Invoice Items:         4210
  • Delivery Decisions:    1000
  • Invoice Files on Disk: 1000 in media/invoices
=================================================================
```

### 5.2 Seeding Statutory Campus Members & Vehicles
Generate 500 students, 100 faculty, 50 residents, 20 staff, 500 vehicles, crossing movements, and overstay scenarios:

```bash
python3 scripts/seed_college_members.py
```

*Generated Statutory Identifiers:*
- **Students (500):** `24103001` through `24103500` (8 numeric digits)
- **Faculty (100):** `F1000001` through `F1000100` (F + 7 digits)
- **Residents (50):** `R1001` through `R1050` (R + 4-digit house number)
- **Staff (20):** `STF-EST-001` through `STF-ADM-020`

### 5.3 Seeding 1,000 Multi-Vendor QR Delivery Invoices
Generate 1,000 realistic delivery invoices with scannable QR codes across major Indian platforms:

```bash
python3 scripts/generate_multivendor_invoices.py
```
- Supported platforms: **Zomato**, **Swiggy**, **Amazon**, **Blinkit**, **Zepto**, **Uber Eats**, **Reliance Fresh**
- Automatically renders PNG images with embedded UPI payment and verification QR codes into [media/invoices/](file:///home/kirat/coding/honours/media/invoices/)
- Populates `delivery_orders`, `invoices`, and `invoice_items` with itemized prices and categories

### 5.4 Purging and Resetting the Dataset
To clean up generated test data while preserving protected administrative accounts:
```bash
# Purge invoices only
python3 scripts/manage_dataset.py --purge-invoices --force

# Purge members and generated vehicles only
python3 scripts/manage_dataset.py --purge-members --force

# Reset all test data
python3 scripts/manage_dataset.py --purge-all --force
```

---

## 6. Running the Services

### 6.1 Launching the FastAPI Backend
Start the backend server on port 8000:

#### Development Mode (Hot-Reload):
```bash
source .venv/bin/activate
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Production Mode (Multi-Worker):
```bash
source .venv/bin/activate
uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-config config/logging.json \
    --access-log
```

Verify service liveness:
```bash
curl -s http://localhost:8000/health/all | jq .
```

### 6.2 Frontend Console Setup & Execution

#### Install Node.js Dependencies:
```bash
cd /home/kirat/coding/honours/frontend
npm install
```

#### Development Mode:
```bash
npm run dev -- --host 0.0.0.0 --port 5173
```
Access the console at `http://localhost:5173`. Default credentials:
- **Username:** `admin` | **Password:** `admin123`
- **Username:** `guard_gate1` | **Password:** `guard123`

#### Production Build & Preview:
```bash
# Compile optimized production bundle
npm run build

# Preview production build locally
npm run preview -- --host 0.0.0.0 --port 4173
```

#### Building Android APK (Capacitor):
```bash
cd /home/kirat/coding/honours/frontend
npx cap sync android
npx cap open android
# Or compile headless APK via Gradle:
cd android && ./gradlew assembleDebug
```
The compiled APK will be generated at `frontend/android/app/build/outputs/apk/debug/app-debug.apk`.

---

## 7. Testing & Quality Assurance Verification

The codebase includes exhaustive test suites covering unit schemas, database constraints, MQTT ingestion, OCR pipelines, and end-to-end integration flows.

### 7.1 Running the Backend Pytest Suite
Run the backend unit and schema test suite using pytest:

```bash
cd /home/kirat/coding/honours
PYTHONPATH=. .venv/bin/pytest backend/tests/ -v
```

To run individual focused test suites:
```bash
# 1. Statutory Institutional ID schema validation
PYTHONPATH=. .venv/bin/pytest backend/tests/test_institutional_id_schema.py -v

# 2. Campus overstay (>1.5h) alert generation
PYTHONPATH=. .venv/bin/pytest backend/tests/test_unlinked_overstay_alert.py -v

# 3. Member and delivery database deletion safety
PYTHONPATH=. .venv/bin/pytest backend/tests/test_deletion_and_purge.py -v

# 4. College members directory & invoice counts
PYTHONPATH=. .venv/bin/pytest backend/tests/test_college_members_and_invoices.py -v
```

### 7.2 Phase-by-Phase Integration Verification Scripts
Execute individual phase verification scripts from the `scripts/` directory:

| Test Script | Tested Subsystem | Command |
| :--- | :--- | :--- |
| `scripts/test_phase1_models.py` | SQLAlchemy ORM Models & Foreign Keys | `python3 scripts/test_phase1_models.py` |
| `scripts/test_phase2_vehicle_api.py` | Vehicle Registry CRUD & Search APIs | `python3 scripts/test_phase2_vehicle_api.py` |
| `scripts/test_phase3_gate_observations.py` | Gate CRUD & Observation Event Ingestion | `python3 scripts/test_phase3_gate_observations.py` |
| `scripts/test_phase4_frigate_mqtt_worker.py` | MQTT Telemetry Parsing & Sanitization | `python3 scripts/test_phase4_frigate_mqtt_worker.py` |
| `scripts/test_phase5c_live_feed.py` | SSE Live Stream & Resolution Feed | `python3 scripts/test_phase5c_live_feed.py` |
| `scripts/test_phase6_movement.py` | Movement Logging & Presence Tracking | `python3 scripts/test_phase6_movement.py` |
| `scripts/test_phase7_delivery_screening.py` | Invoice OCR & Contraband Policy Rules | `python3 scripts/test_phase7_delivery_screening.py` |
| `scripts/test_audit_regressions.py` | Security Audit Hardening Regressions | `python3 scripts/test_audit_regressions.py` |
| `scripts/test_e2e.py` | End-to-End Multi-Pipeline Verification | `python3 scripts/test_e2e.py` |

### 7.3 Standalone Subsystem Probes
```bash
# Verify OCR extraction on sample invoices
python3 scripts/test_ocr.py

# Test MQTT loopback telemetry
python3 scripts/test_frigate_mqtt.py

# Run comprehensive end-to-end integration test
python3 scripts/test_e2e.py
```

---

## 8. Troubleshooting & Common Operational Scenarios

### 8.1 Database Connection Refused (`port 5433`)
- **Symptom:** `psycopg.OperationalError: connection to server at "127.0.0.1", port 5433 failed: Connection refused`
- **Resolution:**
  1. Verify the Docker container is running: `docker ps -f name=campus_postgres`
  2. If stopped, start it: `docker compose up -d postgres`
  3. Confirm the container port mapping in `.env`: `POSTGRES_PORT=5433`

### 8.2 Append-Only Trigger Violation During Maintenance
- **Symptom:** `InternalServerError: Cannot update or delete rows in append-only table entry_exit_logs`
- **Resolution:**
  Administrative cleanup operations must declare the session replica role before executing raw SQL deletions:
  ```sql
  SET LOCAL session_replication_role = 'replica';
  ```
  Alternatively, use the built-in management script:
  ```bash
  python3 scripts/manage_dataset.py --purge-all
  ```

### 8.3 Pytest Module Import Errors
- **Symptom:** `ModuleNotFoundError: No module named 'backend'`
- **Resolution:**
  Ensure the workspace root is on the Python path:
  ```bash
  export PYTHONPATH=/home/kirat/coding/honours
  .venv/bin/pytest backend/tests/
  ```

### 8.4 EventSource / SSE Connection Failures in Guard Console
- **Symptom:** Browser EventSource disconnects repeatedly with 401 Unauthorized.
- **Resolution:**
  Web browser `EventSource` does not support custom HTTP `Authorization` headers. Pass the token via query parameter:
  ```javascript
  const es = new EventSource(`/feed/stream?token=${encodeURIComponent(accessToken)}`);
  ```
  The backend `/feed/stream` endpoint explicitly inspects the `token` query parameter as a fallback when the `Authorization` header is omitted.
