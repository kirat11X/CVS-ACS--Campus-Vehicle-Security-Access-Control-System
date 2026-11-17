# CVS-ACS Production Deployment & AWS EC2 Cloud GPU Training Manual
**Campus Vehicle Security & Access Control System (CVS-ACS)**  
*Deployment Target: Punjab Engineering College (PEC), Sector 12, Chandigarh*  
*Architectural Doctrine: OBSERVE $\rightarrow$ ASSOCIATE $\rightarrow$ CONTEXTUALIZE $\rightarrow$ RECORD $\rightarrow$ ALERT*

---

## Table of Contents
1. [Executive Summary & Production Architecture](#1-executive-summary--production-architecture)
2. [Cloud GPU Infrastructure: AWS EC2 Training Cluster](#2-cloud-gpu-infrastructure-aws-ec2-training-cluster)
3. [Turn-Key EC2 Host Provisioning & Health Certification](#3-turn-key-ec2-host-provisioning--health-certification)
4. [Dataset Automation, Disk Pre-Checks & Checksum Integrity](#4-dataset-automation-disk-pre-checks--checksum-integrity)
5. [Cloud Training Execution Walkthrough & Monitoring](#5-cloud-training-execution-walkthrough--monitoring)
6. [Remote Sync, Checkpoint Recovery & LoRA Artifact Management](#6-remote-sync-checkpoint-recovery--lora-artifact-management)
7. [Production Containerization Architecture](#7-production-containerization-architecture)
8. [Ingress & Reverse Proxy Engineering (Nginx, Vite & Uvicorn)](#8-ingress--reverse-proxy-engineering-nginx-vite--uvicorn)
9. [Bare-Metal & Hybrid Deployment with Systemd](#9-bare-metal--hybrid-deployment-with-systemd)
10. [Disaster Recovery, Automated Backups & Restoration](#10-disaster-recovery-automated-backups--restoration)
11. [Zero-Downtime Rolling Updates & Database Migration](#11-zero-downtime-rolling-updates--database-migration)
12. [Operational Runbooks & Incident Response Playbook](#12-operational-runbooks--incident-response-playbook)

---

## 1. Executive Summary & Production Architecture

The Campus Vehicle Security & Access Control System (**CVS-ACS**) operates across a hybrid edge-cloud paradigm engineered specifically for high-throughput, latency-critical institutional security. The system monitors three primary perimeter gates at Punjab Engineering College (PEC):

* **Gate 1 (Main Entrance - Vidya Path / Sector 12):** Mixed vehicle traffic (faculty cars, student two-wheelers, VIP convoys, commercial delivery vans).
* **Gate 2 (Hostel Perimeter - Sector 11 Side):** Heavy quick-commerce delivery traffic (Blinkit, Zepto, Swiggy Instamart, Zomato) and student pedestrian/motorcycle movements.
* **Gate 3 (Service & Staff Entrance):** Maintenance vehicles, supply trucks, construction equipment, and contractor entries.

```
                              CVS-ACS TOPOLOGY OVERVIEW

  +-------------------------------------------------------------------------------+
  |                          AWS CLOUD TRAINING CLUSTER                           |
  |   (EC2 g4dn.xlarge / g5.xlarge Spot Instances: $0.158/hr - $0.302/hr)         |
  |                                                                               |
  |   +-----------------------+ +--------------------+ +----------------------+   |
  |   | Track A: OCR CCT      | | Track B: VLM Qwen3 | | Track C: LLM Screen  |   |
  |   | (KERAS_BACKEND=torch) | | (4-bit QLoRA)      | | (Calibrated Qwen1.7) |   |
  |   +-----------------------+ +--------------------+ +----------------------+   |
  +---------------------------------------+---------------------------------------+
                                          | Checkpoint Sync via rsync / S3
                                          v
  +-------------------------------------------------------------------------------+
  |                      ON-PREMISE CAMPUS PRODUCTION SERVER                      |
  |   (Dell PowerEdge / NVIDIA RTX Edge Workstation - Ubuntu 24.04 LTS)           |
  |                                                                               |
  |   [ Reverse Proxy Ingress: Nginx (Port 80/443, SSL/TLS, WebSockets, Gzip) ]   |
  |             |                                                |                |
  |             v                                                v                |
  |   [ Vite React Console SPA ]                       [ FastAPI Core Backend ]   |
  |   (Gate Guard PWA, Port 80)                        (Uvicorn 4 Workers, :8000) |
  |                                                              |                |
  |             +------------------------------------------------+                |
  |             v                                                v                |
  |   [ Eclipse Mosquitto Broker ]                     [ PostgreSQL 16 Store ]    |
  |   (MQTT Pub/Sub, Port 1883)                        (Relational Data, :5433)   |
  |             ^                                                |                |
  |             |                                                v                |
  |   [ Frigate NVR Subsystem ]                        [ n8n Workflow Engine ]    |
  |   (RTSP Stream Ingest, OpenCV, :5000)              (Webhooks & Alerts, :5678) |
  +-------------------------------------------------------------------------------+
        ^                   ^                   ^
        | RTSP Feed         | RTSP Feed         | RTSP Feed
  +-------------+     +-------------+     +-------------+
  | Gate 1 Cam  |     | Gate 2 Cam  |     | Gate 3 Cam  |
  | (LPR+Detect)|     | (LPR+Detect)|     | (LPR+Detect)|
  +-------------+     +-------------+     +-------------+
```

---

## 2. Cloud GPU Infrastructure: AWS EC2 Training Cluster

Heavy neural network training (Compact Convolutional Transformers for ANPR OCR, 4-bit QLoRA fine-tuning of `Qwen3-VL-2B`, and safety-calibrated `Qwen3-1.7B` LLM screening) requires dedicated NVIDIA Tensor Core hardware.

### 2.1 Recommended EC2 Instance Matrix

| Instance Tier | Accelerator | VRAM | vCPUs | System RAM | On-Demand Rate | Spot Rate (Typical) | Best Operational Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`g4dn.xlarge`** *(Recommended)* | 1x NVIDIA Tesla T4 | **16 GB** | 4 | 16 GB | \$0.526 / hr | **\$0.158 / hr** *(70% savings)* | Track A OCR (CCT), Track C LLM QLoRA, Smoke Tests |
| **`g5.xlarge`** | 1x NVIDIA A10G | **24 GB** | 4 | 16 GB | \$1.006 / hr | **\$0.302 / hr** | Track B `Qwen3-VL-2B` fine-tuning (2.5x throughput) |
| **`g4dn.2xlarge`** | 1x NVIDIA Tesla T4 | **16 GB** | 8 | 32 GB | \$0.752 / hr | **\$0.225 / hr** | Multi-worker dataset rendering + concurrent training |

> [!TIP]
> **Spot Instance Interruption Strategy:**  
> Spot instances deliver up to 70% cost reduction. All CVS-ACS training scripts (`ec2/train_track_a_ocr.sh`, `ec2/train_track_b_vlm.sh`, `ec2/train_track_c_llm.sh`) automatically save incremental epoch checkpoints (`best_model.pt`, `adapter_model.safetensors`, `training_metrics.json`). In the event of a 2-minute AWS spot reclamation notice, state is persisted and resumed seamlessly upon re-launch.

### 2.2 AWS IAM Instance Profile & Firewall Topology

Attach an IAM Role with the following policies:
* `AmazonSSMManagedInstanceCore`: Enables AWS Systems Manager Session Manager terminal access without exposing public port 22.
* `AmazonS3FullAccess` *(Optional)*: For automated weights replication to an encrypted S3 bucket (`s3://pec-cvs-acs-weights/`).

#### Security Group Inbound Ingress Rules

| Protocol | Port Range | Source | Operational Function |
| :--- | :--- | :--- | :--- |
| **SSH** | `22` | `PEC_ADMIN_IP/32` | Secure remote shell access (or SSM Session) |
| **Custom TCP**| `8000` | `PEC_ADMIN_IP/32` | FastAPI Backend API (`/docs`, `/metrics`) |
| **Custom TCP**| `5000` | `PEC_ADMIN_IP/32` | Frigate NVR Web Console |
| **Custom TCP**| `5173` | `PEC_ADMIN_IP/32` | Vite React Guard Console |
| **Custom TCP**| `1883` | `PEC_ADMIN_IP/32` | Mosquitto MQTT Telemetry Broker |

> [!CAUTION]
> Never open ingress ports to `0.0.0.0/0`. For zero-exposure development, forward all ports locally via an encrypted SSH tunnel:
> ```bash
> ssh -i ~/.ssh/cvs-acs-key.pem -N \
>     -L 8000:localhost:8000 \
>     -L 5000:localhost:5000 \
>     -L 5173:localhost:5173 \
>     -L 1883:localhost:1883 \
>     ubuntu@<EC2_PUBLIC_IP>
> ```

---

## 3. Turn-Key EC2 Host Provisioning & Health Certification

### 3.1 Step-by-Step Provisioning Runbook

1. **Connect to the EC2 Host:**
   ```bash
   ssh -i ~/.ssh/cvs-acs-key.pem ubuntu@<EC2_PUBLIC_DNS>
   ```

2. **Clone the CVS-ACS Repository:**
   ```bash
   git clone https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System.git honours
   cd honours
   chmod +x ec2/*.sh scripts/*.py scripts/*.sh
   ```

3. **Execute Automated Provisioning:**
   The turn-key setup script [`ec2/setup_ec2_gpu.sh`](file:///home/kirat/coding/honours/ec2/setup_ec2_gpu.sh) handles complete host configuration:
   * Installs build essentials, multimedia libraries (`libgl1`, `libglib2.0-0`, `ffmpeg`, `libsm6`), and `jq`.
   * Provisions NVIDIA Tesla Server Driver (550+) and CUDA 12.4 runtime.
   * Configures Docker Engine with the official NVIDIA Container Toolkit (`nvidia-ctk`).
   * Bootstraps `uv` and Python 3.12 ML virtual environment at `~/ml-assets/campus/.venv-ml`.
   * Installs PyTorch (CUDA 12.4 wheels), Transformers, PEFT, bitsandbytes (4-bit QLoRA), TRL, Accelerate, Keras 3, Ultralytics YOLO11, and `fast-plate-ocr`.
   * Enforces persistent environment variables in `~/.bashrc`:
     ```bash
     export KERAS_BACKEND=torch
     export CUDA_VISIBLE_DEVICES=0
     export HF_HOME="$HOME/ml-assets/campus/hf"
     export PATH="$HOME/.local/bin:$HOME/ml-assets/campus/.venv-ml/bin:$PATH"
     ```

   ```bash
   ./ec2/setup_ec2_gpu.sh
   ```

### 3.2 Running the Diagnostic Certification Healthcheck

Execute [`ec2/ec2_healthcheck.sh`](file:///home/kirat/coding/honours/ec2/ec2_healthcheck.sh) to audit all 7 hardware, system, and neural framework subsystems:
```bash
./ec2/ec2_healthcheck.sh
```

**Diagnostic Verification Output:**
```text
======================================================================
            CVS-ACS AWS EC2 SYSTEM & ML HEALTHCHECK           
======================================================================
1. GPU & CUDA ACCELERATION:
  [PASS] NVIDIA Driver: 550.90.07 | CUDA: 12.4
  [PASS] GPU Device:   Tesla T4
  [PASS] VRAM:         15109 MiB free / 15360 MiB total
  [PASS] Thermals:     38°C | Power: 26.14 W

2. SYSTEM RESOURCES (RAM & CPU):
  [PASS] System RAM:   14.2 GB available / 15.8 GB total
  [PASS] CPU Cores:    4 vCPUs | Load: 0.12 (1m), 0.08 (5m)

3. STORAGE & DISK CAPACITY:
  [PASS] Root Disk:    78 GB free / 100 GB total

4. DOCKER & NVIDIA CONTAINER RUNTIME:
  [PASS] Docker Daemon: Running (27.3.1)
  [PASS] NVIDIA Container Runtime: Configured in Docker

5. PYTHON ML STACK & PYTORCH ACCELERATION:
  [PASS] Virtualenv:   /home/ubuntu/ml-assets/campus/.venv-ml
  [PASS] Python Version: 3.12.7
  [PASS] PyTorch:       2.4.1+cu124
  [PASS] PyTorch CUDA:  ACTIVE (Tesla T4)
  [PASS] GPU Benchmark: Matrix 4096x4096 in 18.2 ms

6. INSTALLED ML & TRAINING PACKAGES:
  [PASS] Keras 3:       v3.6.0 (KERAS_BACKEND=torch)
  [PASS] Transformers:  v4.45.2
  [PASS] PEFT (LoRA):   v0.13.2
  [PASS] bitsandbytes:  v0.44.1 (4-bit QLoRA ready)
  [PASS] Ultralytics:   v8.3.16 (YOLO11 ready)

======================================================================
                       DIAGNOSTIC SCORECARD                          
======================================================================
  Passed Checks:    18
  Warnings:         0
  Critical Failures:0

==> EC2 GPU HOST IS FULLY CERTIFIED AND READY FOR ML TRAINING! <==
```

---

## 4. Dataset Automation, Disk Pre-Checks & Checksum Integrity

Dataset management is fully automated via [`scripts/download_datasets.py`](file:///home/kirat/coding/honours/scripts/download_datasets.py).

### 4.1 Automated Safeguards
* **Storage Capacity Pre-Flight Check:** `check_disk_space()` audits available storage before ingestion, requiring $\ge 10.0\text{ GB}$ for all tracks, $\ge 5.0\text{ GB}$ for Track A, $\ge 3.0\text{ GB}$ for Track B, and $\ge 1.0\text{ GB}$ for Track C.
* **Stream Resumption:** HTTP/HTTPS downloads support byte-range resumption (`Range: bytes=...`) with `.download.tmp` staging.
* **Cryptographic Validation:** Validates SHA-256 hashes against canonical fixtures (e.g., canonical item taxonomy seed `a87326d5...`).

### 4.2 Dataset CLI Ingestion & Verification Commands

```bash
# Ingest and stage all datasets across Track A, B, and C:
python3 scripts/download_datasets.py --all

# Download individual research tracks:
python3 scripts/download_datasets.py --track-a
python3 scripts/download_datasets.py --track-b
python3 scripts/download_datasets.py --track-c

# Run dry-run integrity verification and generate JSON audit report:
python3 scripts/download_datasets.py --verify --target-dir data/datasets
```

---

## 5. Cloud Training Execution Walkthrough & Monitoring

All long-running training jobs must run inside persistent `tmux` sessions. Each script includes automatic `$TMUX` detection and alerts the operator if run unprotected.

### 5.1 Track A: ANPR Second-Reader OCR (CCT Architecture)
Trains `cct_s_v2_global.keras` with `KERAS_BACKEND=torch` on the canonical `prepared/ocr_in_v1` dataset (13,698 crops):

```bash
# 1. Open persistent session
tmux new -s train_track_a

# 2. Launch OCR training
./ec2/train_track_a_ocr.sh --epochs 50 --batch-size 64 --lr 0.001

# (Optional: Quick smoke test)
./ec2/train_track_a_ocr.sh --smoke-test
```
* **Weights Export:** `weights/track_a_ocr_cct.pt` and `weights/track_a_ocr_cct.onnx`.
* **Metrics:** `weights/track_a_ocr_metrics.json`.

### 5.2 Track B: Delivery Invoice Parsing (Qwen3-VL-2B QLoRA)
Fine-tunes `Qwen/Qwen3-VL-2B-Instruct` in 4-bit NormalFloat4 (NF4) with Double Quantization:

```bash
# 1. Open persistent session
tmux new -s train_track_b

# 2. Launch VLM fine-tuning
./ec2/train_track_b_vlm.sh --epochs 3 --batch-size 2 --grad-accum 8 --lr 2e-4
```
* **Adapter Export:** `weights/track_b_qwen3_vl_lora/` (`adapter_model.safetensors`, `adapter_config.json`).
* **Metrics:** `weights/track_b_vlm_metrics.json`.

### 5.3 Track C: Prohibited Item Screening (Qwen3-1.7B LLM)
Trains and calibrates `Qwen/Qwen3-1.7B` on the canonical 320-item taxonomy across 8 security categories with temperature scaling ($T=1.24$) and calibrated thresholding ($\ge 0.70$ confidence):

```bash
# 1. Open persistent session
tmux new -s train_track_c

# 2. Launch LLM fine-tuning and calibration
./ec2/train_track_c_llm.sh --epochs 6 --lr 2e-4
```
* **Adapter Export:** `weights/track_c_qwen3_1.7b_lora/` (`adapter_model.safetensors`, `calibration_config.json`).
* **Metrics:** `weights/track_c_llm_metrics.json`.

### 5.4 Session & Telemetry Management Cheat Sheet

```bash
# Detach from active tmux session:
Press [Ctrl + B], release, then press [D]

# List active training sessions:
tmux ls

# Re-attach to a running job:
tmux attach -t train_track_a
tmux attach -t train_track_b
tmux attach -t train_track_c

# Real-time graphical GPU monitor:
nvtop

# Continuous VRAM and power telemetry:
watch -n 1 nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.free,power.draw,temperature.gpu --format=table
```

---

## 6. Remote Sync, Checkpoint Recovery & LoRA Artifact Management

Trained neural weights and LoRA adapters must be transferred between cloud compute and campus production edge nodes with zero corruption.

### 6.1 Checkpoint Artifact Inventory

| Track | Primary Artifact Path | Supplementary Files | Target Runtime Role |
| :--- | :--- | :--- | :--- |
| **Track A** | `weights/track_a_ocr_cct.pt` | `weights/track_a_ocr_cct.onnx`, `track_a_ocr_metrics.json` | High-speed CCT plate OCR fallback |
| **Track B** | `weights/track_b_qwen3_vl_lora/adapter_model.safetensors` | `adapter_config.json`, `training_metrics.json` | Quick-commerce invoice OCR extraction |
| **Track C** | `weights/track_c_qwen3_1.7b_lora/adapter_model.safetensors` | `calibration_config.json`, `training_metrics.json` | Access control contraband classifier |

### 6.2 Checkpoint Synchronization Utility: `scripts/sync_checkpoints.sh`

A dedicated sync script [`scripts/sync_checkpoints.sh`](file:///home/kirat/coding/honours/scripts/sync_checkpoints.sh) is provided:

```bash
# Pull all weights and adapters from EC2 to campus server:
./scripts/sync_checkpoints.sh pull \
    --host ubuntu@<EC2_PUBLIC_IP> \
    --key ~/.ssh/cvs-acs-key.pem \
    --remote-path ~/coding/honours

# Push local weights to remote EC2 instance:
./scripts/sync_checkpoints.sh push \
    --host ubuntu@<EC2_PUBLIC_IP> \
    --key ~/.ssh/cvs-acs-key.pem
```

#### Under the Hood: Resilient `rsync` Transfer Flags
```bash
rsync -avhP \
    --partial \
    --append-verify \
    --update \
    --exclude="*.tmp" \
    --exclude="*__pycache__*" \
    -e "ssh -i ~/.ssh/cvs-acs-key.pem" \
    ubuntu@<EC2_PUBLIC_IP>:~/coding/honours/weights/ \
    /home/kirat/coding/honours/weights/
```
* `--partial`: Preserves partially transferred blocks if network drops.
* `--append-verify`: Efficiently resumes multi-gigabyte safetensors/weights files and runs internal checksums.
* `--update`: Skips files that are newer on the destination.

---

## 7. Production Containerization Architecture

The entire CVS-ACS suite is orchestrated via [`docker-compose.prod.yml`](file:///home/kirat/coding/honours/docker-compose.prod.yml).

### 7.1 Microservice Topology & Ports

```
                                  +-------------------+
                                  |   Client / Guard  |
                                  +---------+---------+
                                            | Port 80 / 443
                                            v
                      +-----------------------------------------------+
                      |            campus_nginx (:80/:443)            |
                      +-------+-------------------+---------------+---+
                              |                   |               |
               /api/          |                   | /             | /frigate/
               +--------------+                   +-------+       +--------+
               |                                          |                |
               v                                          v                v
+-------------------------------+             +-----------------------+  +-------------------+
|     campus_backend (:8000)    |             | campus_frontend (:80) |  |   campus_frigate  |
|  (FastAPI + MQTT Worker)      |             | (Vite React Nginx)    |  |  (:5000 / :8554)  |
+-------+---------------+-------+             +-----------------------+  +---------+---------+
        |               |                                                          |
        v               v                                                          v
+---------------+ +---------------+                                        +-------+---------+
|campus_postgres| |campus_mosquitt| <--------------------------------------+ MQTT telemetry  |
|  (:5433)      | |  (:1883)      |                                        | /frigate/events |
+---------------+ +---------------+                                        +-----------------+
```

### 7.2 Service Specifications

1. **`campus_nginx` (`nginx:1.27-alpine`):** Ingress gateway handling reverse proxying, client body buffers (50 MB), Gzip compression, and WebSocket connection upgrading.
2. **`campus_backend` ([`backend/Dockerfile`](file:///home/kirat/coding/honours/backend/Dockerfile)):** Python 3.12 slim image with Tesseract, OpenCV, FFmpeg, Uvicorn, and background MQTT worker.
3. **`campus_frontend` ([`frontend/Dockerfile`](file:///home/kirat/coding/honours/frontend/Dockerfile)):** Multi-stage build (Node 22 $\rightarrow$ Nginx Alpine) serving the Vite React SPA console.
4. **`campus_frigate` (`ghcr.io/blakeblackshear/frigate:stable`):** NVR camera ingestion pipeline, hardware-accelerated video decoding, object tracking, and LPR.
5. **`campus_postgres` (`postgres:16-alpine`):** Relational database with healthcheck (`pg_isready`) and persistent named volume `postgres_data`.
6. **`campus_mosquitto` (`eclipse-mosquitto:2`):** MQTT telemetry message bus connecting Frigate to the FastAPI ingestion worker.
7. **`campus_n8n` (`docker.n8n.io/n8nio/n8n:latest`):** Low-code workflow automation orchestrating SMS/WhatsApp alerts and security escalation.

### 7.3 Launching the Production Stack

```bash
# 1. Configure environment
cp .env.example .env
nano .env

# 2. Build and launch all microservices in detached mode
docker compose -f docker-compose.prod.yml up -d --build

# 3. Verify service health status
docker compose -f docker-compose.prod.yml ps

# 4. Tail aggregated logs
docker compose -f docker-compose.prod.yml logs -f --tail=100
```

---

## 8. Ingress & Reverse Proxy Engineering (Nginx, Vite & Uvicorn)

The Nginx configuration ([`config/nginx/nginx.conf`](file:///home/kirat/coding/honours/config/nginx/nginx.conf) and [`config/nginx/cvs-acs.conf`](file:///home/kirat/coding/honours/config/nginx/cvs-acs.conf)) enforces enterprise security and routing standards:

### 8.1 Critical Routing Rules
* **API Ingress (`/api/`):** Rewrites `^/api/(.*)` to `/$1` and proxies to `http://backend_upstream` (Uvicorn).
* **WebSocket Ingress (`/ws`):** Hands off HTTP upgrades to WebSockets with `proxy_read_timeout 3600s;`.
* **Guard Console (`/`):** Proxies to `http://frontend_upstream` with client-side HTML5 pushState routing support (`try_files $uri $uri/ /index.html;`).
* **Static Snapshots (`/media/`):** Direct alias to high-speed disk storage with 7-day browser caching.
* **Large File Uploads:** Configured with `client_max_body_size 50M;` to support high-resolution multi-page delivery invoice scans and raw camera captures.

---

## 9. Bare-Metal & Hybrid Deployment with Systemd

For on-premise installations where Docker overhead is discouraged or direct GPU access is required without containerization, CVS-ACS provides complete systemd service units.

### 9.1 Unit Manifests

| Service Unit | File Location | Purpose |
| :--- | :--- | :--- |
| **Compose Daemon** | [`systemd/cvs-acs-compose.service`](file:///home/kirat/coding/honours/systemd/cvs-acs-compose.service) | Manages full Docker Compose stack lifecycle on system boot |
| **FastAPI Backend** | [`systemd/cvs-acs-backend.service`](file:///home/kirat/coding/honours/systemd/cvs-acs-backend.service) | Bare-metal Uvicorn process manager (4 workers) |
| **DB Backup Service**| [`systemd/cvs-acs-db-backup.service`](file:///home/kirat/coding/honours/systemd/cvs-acs-db-backup.service) | One-shot PostgreSQL database backup execution |
| **DB Backup Timer** | [`systemd/cvs-acs-db-backup.timer`](file:///home/kirat/coding/honours/systemd/cvs-acs-db-backup.timer) | Systemd timer running daily backups at 02:30 AM |

### 9.2 Installing & Enabling Systemd Services

```bash
# Copy systemd units to system directory
sudo cp systemd/cvs-acs-compose.service /etc/systemd/system/
sudo cp systemd/cvs-acs-db-backup.service /etc/systemd/system/
sudo cp systemd/cvs-acs-db-backup.timer /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable automatic start on system boot
sudo systemctl enable --now cvs-acs-compose.service
sudo systemctl enable --now cvs-acs-db-backup.timer

# Check active timer schedule
systemctl list-timers cvs-acs-db-backup.timer
```

---

## 10. Disaster Recovery, Automated Backups & Restoration

Data integrity is mission-critical: loss of vehicle observation records or delivery screening logs compromises campus physical security.

### 10.1 Backup Architecture: `scripts/backup_db.sh`

The backup automation script [`scripts/backup_db.sh`](file:///home/kirat/coding/honours/scripts/backup_db.sh) executes:
1. Online `pg_dump` with `--clean --if-exists` flags (non-blocking for ongoing vehicle logging).
2. Streaming compression via `gzip`.
3. Cryptographic SHA-256 integrity checksum generation (`.sha256`).
4. Automatic pruning of archives older than 14 days (`RETENTION_DAYS=14`).
5. Optional upload to AWS S3 (`s3://pec-cvs-acs-backups/postgres/`).

```bash
# Manual backup execution:
./scripts/backup_db.sh --retention-days 14
```

### 10.2 Point-in-Time Database Restoration: `scripts/restore_db.sh`

The disaster recovery utility [`scripts/restore_db.sh`](file:///home/kirat/coding/honours/scripts/restore_db.sh) provides safe point-in-time recovery:
1. Validates the archive SHA-256 checksum prior to execution.
2. Gracefully terminates active client locks on the target database (`pg_terminate_backend`).
3. Streams decompressed SQL into PostgreSQL via Docker or local `psql`.

```bash
# Restore from a backup archive:
./scripts/restore_db.sh /var/backups/cvs-acs/postgres/campus_security_20261117_030000.sql.gz
```

---

## 11. Zero-Downtime Rolling Updates & Database Migration

To deploy software updates without dropping incoming gate camera feeds or guard API calls:

```
ZERO-DOWNTIME ROLLING UPDATE SEQUENCE

  1. Git Pull / Checkout Tag
            |
            v
  2. Build New Images: docker compose -f docker-compose.prod.yml build
            |
            v
  3. Safe Database Migration: docker exec -i campus_backend alembic upgrade head
            |
            v
  4. Rolling Container Replacement: docker compose -f docker-compose.prod.yml up -d --no-deps backend
            |
            v
  5. Health Probe Verification: curl -f http://localhost:8000/health
            |
            v
  6. Reload Reverse Proxy: docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### 11.1 Step-by-Step Production Update Procedure

```bash
# Step 1: Pull verified release tag
git fetch origin && git checkout v0.7.0

# Step 2: Build container images in background
docker compose -f docker-compose.prod.yml build

# Step 3: Execute non-destructive Alembic migrations
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head

# Step 4: Recreate backend container (Uvicorn workers reload gracefully)
docker compose -f docker-compose.prod.yml up -d --no-deps backend

# Step 5: Wait for backend healthcheck to pass
until [ "$(docker inspect -f '{{.State.Health.Status}}' campus_backend)" = "healthy" ]; do
    echo "Waiting for backend healthcheck..."
    sleep 2
done

# Step 6: Update frontend and reload Nginx
docker compose -f docker-compose.prod.yml up -d --no-deps frontend
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

---

## 12. Operational Runbooks & Incident Response Playbook

### Incident 1: GPU Out-Of-Memory (OOM) during VLM Inference/Training
* **Symptoms:** PyTorch throws `torch.cuda.OutOfMemoryError: CUDA out of memory`.
* **Remediation:**
  1. Audit active GPU processes: `nvidia-smi`
  2. Kill orphaned PyTorch/Python workers: `pkill -9 -f python`
  3. Ensure 4-bit BitsAndBytes quantization (`load_in_4bit=True`, `bnb_4bit_quant_type="nf4"`) is enabled.
  4. Enable PyTorch gradient checkpointing and reduce per-device batch size to 1 with gradient accumulation (`--grad-accum 8`).

### Incident 2: MQTT Broker Disconnect / Frigate Stream Drop
* **Symptoms:** Gate observations stall; guard console shows "MQTT Reconnecting".
* **Remediation:**
  1. Inspect Mosquitto container status: `docker logs campus_mosquitto --tail=50`
  2. Verify network bridge connectivity: `docker exec campus_backend ping mosquitto`
  3. Restart Mosquitto and trigger worker reconnect:
     ```bash
     docker compose -f docker-compose.prod.yml restart mosquitto
     docker compose -f docker-compose.prod.yml restart backend
     ```

### Incident 3: PostgreSQL Connection Pool Saturation
* **Symptoms:** HTTP 500 errors with `psycopg.OperationalError: FATAL: remaining connection slots are reserved`.
* **Remediation:**
  1. Inspect active connection count:
     ```bash
     docker exec -it campus_postgres psql -U campus_admin -d campus_security \
         -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
     ```
  2. Kill idle connections older than 10 minutes:
     ```bash
     docker exec -it campus_postgres psql -U campus_admin -d campus_security \
         -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND state_change < current_timestamp - INTERVAL '10' MINUTE;"
     ```
  3. Adjust `max_connections` in `postgresql.conf` if peak gate activity exceeds pool limits.

---
*Manual Version: 2.0.0 | Release: November 2026 | CVS-ACS Production Infrastructure & Compute Engineering*
