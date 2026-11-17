# WHAT HAS TO BE DONE
## Campus Vehicle Security & Access-Control System (CVS-ACS)
### Comprehensive Engineering Backlog, Cloud GPU Training Protocols, Hardware Deployment & Barrier Controller Integration Roadmap

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Workspace Directory:** [/home/kirat/coding/honours](file:///home/kirat/coding/honours)  
**Target Deployment Site:** Punjab Engineering College (PEC), Sector 12, Chandigarh (`GATE_1`, `GATE_2`, `GATE_3`)  
**Target Delivery Window:** 4–6 Weeks (Core Pilot) to 3 Months (Full Campus Production)  
**Guiding Mandate:** Physical gates remain under 100% human security control. AI/ML assists, flags, and audits; human guards decide.

---

## 1. Executive Summary of Remaining Work

With the core foundational infrastructure, database schema (19 models), security hardening (27 commits), FastAPI backend (17 routers), React 19 console (17 pages), statutory institutional member directory (670+ members, 500+ vehicles), 1,000 multi-vendor QR delivery invoices, overstay alert detection, and administrative deletion tools fully operational in `main`, **~25–30% of total engineering scope remains** to reach full campus production.

```
+-------------------------------------------------------------------------------------------------------+
|                                    TOTAL REMAINING WORKSTREAM MATRIX                                  |
+------------------------------------+--------------------------+-----------------------+---------------+
| Workstream                         | Current Completion       | Target Completion     | Primary Venue |
+------------------------------------+--------------------------+-----------------------+---------------+
| 1. Local Code Hygiene & Adapters   | 90%                      | 100% (Day 1-3)        | Local Host    |
| 2. Cloud GPU Model Training        | 40%                      | 100% (Weeks 1-2)      | AWS EC2 Spot  |
| 3. Physical Camera & Lighting Site | 25%                      | 100% (Weeks 2-3)      | PEC Gates 1-3 |
| 4. WhatsApp Business Cloud API     | 60%                      | 100% (Weeks 3-4)      | Meta Cloud API|
| 5. Barrier Controller Integration  | 15%                      | 100% (Weeks 4-6)      | On-Site Gates |
| 6. Production Ops & Pilot Shadow   | 30%                      | 100% (Weeks 5-8)      | PEC Production|
+------------------------------------+--------------------------+-----------------------+---------------+
```

The remaining work is divided into four concrete execution tiers:
1. **Tier 1: Cloud GPU Model Training on AWS EC2** (High-throughput OCR, VLM, and LLM fine-tuning)
2. **Tier 2: On-Site Hardware Deployment & Sensor Calibration at PEC Gates 1–3** (Mounting, optics, lighting)
3. **Tier 3: Barrier Controller & Hardware Interlock Integration** (Relay boards, industrial I/O, safety loops)
4. **Tier 4: Enterprise Production Hardening, TLS & Shadow Pilot** (Nginx, Sentry, Meta Cloud API, Grafana)

---

## 2. Tier 1: Cloud GPU Model Training on AWS EC2

Local hardware (NVIDIA GeForce RTX 4050 Laptop GPU with 6 GB VRAM) is constrained by memory ceilings when fine-tuning Vision-Language Models (VLMs) and large sequence encoders. Local training of Track A OCR also encountered RAM starvation from GNOME desktop processes. Compute-intensive training must execute remotely on AWS EC2.

### 2.1 AWS EC2 GPU Infrastructure Provisioning
- **Target Instance Type:** AWS EC2 `g4dn.xlarge` (4 vCPUs, 16 GB System RAM, 1x NVIDIA Tesla T4 GPU with 16 GB GDDR6 VRAM, 125 GB NVMe SSD) or `g5.xlarge` (1x NVIDIA A10G with 24 GB VRAM).
- **Operating System:** Ubuntu 22.04 LTS (Deep Learning AMI with CUDA 12.2 and PyTorch 2.4).
- **Spot Orchestration Scripts:** Utilize existing automation under [research_track/hitl_anpr/aws/](file:///home/kirat/coding/honours/research_track/hitl_anpr/aws/):
  - [cloudformation.yaml](file:///home/kirat/coding/honours/research_track/hitl_anpr/aws/cloudformation.yaml): Automated VPC, security group, and spot instance provisioning.
  - [launch_train.sh](file:///home/kirat/coding/honours/research_track/hitl_anpr/aws/launch_train.sh): Remote training orchestration, data sync, and checkpoint export.
  - [spot_handler.sh](file:///home/kirat/coding/honours/research_track/hitl_anpr/aws/spot_handler.sh): Interruption handling and graceful checkpoint sealing to S3.
  - [idle_stop.sh](file:///home/kirat/coding/honours/research_track/hitl_anpr/aws/idle_stop.sh): Auto-shutdown after 15 minutes of GPU inactivity to prevent cost overruns.

### 2.2 Track A: CCT License Plate OCR Fine-Tuning
- **Objective:** Upgrade optical character recognition from the baseline CRNN (63.12% exact accuracy) to a Compact Convolutional Transformer (CCT) model.
- **Root Cause of Local Blocker:** Local TensorFlow failed to bind CUDA on Linux kernel 7.1.13; running concurrent object detection and OCR on the 6 GB RTX 4050 caused CUDA Out-Of-Memory (OOM).
- **Cloud Execution Steps:**
  ```bash
  # On AWS EC2 instance:
  git clone https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System.git
  cd CVS-ACS--Campus-Vehicle-Security-Access-Control-System
  python3.12 -m venv .venv_gpu && source .venv_gpu/bin/activate
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
  pip install keras==3.4.1 albumentations opencv-python-headless onnx tf2onnx

  # Configure PyTorch backend for Keras 3
  export KERAS_BACKEND=torch
  export CUDA_VISIBLE_DEVICES=0

  # Train CCT-S-v2 on 14,700+ combined real Indian crops
  python scripts/train_ocr_extended.py \
      --model cct_s_v2 \
      --epochs 150 \
      --batch-size 128 \
      --lr 5e-4 \
      --output-dir weights/cct_ocr_ec2/
  ```
- **Target Metrics:** Exact plate recognition accuracy $\ge 85.0\%$, Character Error Rate (CER) $\le 3.0\%$.
- **Model Export:** Export final PyTorch checkpoint to ONNX ([weights/cct_plate_ocr_best.onnx](file:///home/kirat/coding/honours/weights/)) and INT8 quantized TFLite.

### 2.3 Track B: Invoice VLM Fine-Tuning (`Qwen3-VL-2B-Instruct`)
- **Target Model:** `Qwen/Qwen3-VL-2B-Instruct` (2 billion parameters, Vision-Language multimodal).
- **Training Strategy:**
  - 4-bit quantization via `bitsandbytes` (QLoRA) with LoRA rank $r=16, \alpha=32$ on attention projection layers.
  - Training dataset:
    - Pretraining: `naver-clova-ix/cord-v2` (~1,000 receipts) and `katanaml-org/invoices-donut-data-v1` (500 invoices).
    - Indian quick-commerce adaptation: 1,000 multi-vendor QR delivery invoices generated in [media/invoices/](file:///home/kirat/coding/honours/media/invoices/) (Zomato, Swiggy, Blinkit, Zepto, Amazon, Reliance).
- **Target Metrics:**
  - Valid JSON generation rate: **> 98.0%**.
  - Key financial field extraction (Total, Subtotal, Order ID) F1 score: **> 95.0%**.
  - Line-item description and price extraction F1 score: **> 90.0%**.

### 2.4 Track C: Real Campus Quick-Commerce Item Calibration
- **Model:** `Qwen/Qwen3-1.7B` + `full_c_v1` QLoRA.
- **Production Safety Calibration:**
  - Collect 500+ real delivery line items from Swiggy Instamart, Blinkit, and Zomato receipts physically entering PEC Gate 2.
  - Human review and label items into the canonical 8 categories ([research_track/datasets/item_taxonomy_seed/seed_items.csv](file:///home/kirat/coding/honours/research_track/datasets/item_taxonomy_seed/seed_items.csv)).
  - Calibrate temperature and output logits so ambiguous items safely yield `is_uncertain=True` and escalate to `REVIEW`.

---

## 3. Tier 2: On-Site Hardware Deployment & Sensor Calibration at PEC Gates 1–3

A computer vision pipeline trained solely on open datasets experiences significant domain shift when deployed in a live campus environment. The physical camera network must be calibrated directly at the three PEC entry points.

```
                    +-------------------------------------------------------+
                    |          PEC CAMPUS PERIMETER CAMERA NETWORK          |
                    +-------------------------------------------------------+
                                                |
         +--------------------------------------+--------------------------------------+
         |                                      |                                      |
         v                                      v                                      v
+-------------------------------+  +-------------------------------+  +-------------------------------+
|       GATE 1: MAIN GATE       |  |     GATE 2: HOSTEL GATE       |  |      GATE 3: STAFF GATE       |
| 4 Lanes: 2 Entry / 2 Exit     |  | 2 Lanes: 1 Entry / 1 Exit     |  | 2 Lanes: Bidirectional        |
| Speed: 15-25 km/h (Speed Bump)|  | Speed: 5-15 km/h (Bollards)   |  | Speed: 10-20 km/h (Security)  |
| Lighting: High LED Floodlights|  | Lighting: Low Ambient Light   |  | Lighting: Tree Shadow Glare   |
| Traffic: Buses, Cars, Couriers|  | Traffic: 2-Wheelers, Swiggy   |  | Traffic: Faculty Sedans, SUVs |
+-------------------------------+  +-------------------------------+  +-------------------------------+
```

### 3.1 Optical Camera Mounting Geometry & Specifications
For each gate lane, enforce physical installation guidelines:
- **Mounting Height:** $2.2\text{ m} - 2.5\text{ m}$ above the road surface (prevents occlusion from leading tall vehicles while avoiding steep distortion).
- **Approach Angle:** $15^\circ - 25^\circ$ horizontal angle relative to the vehicle's line of travel (avoids direct retro-reflective specular glare from headlights).
- **Camera Resolution & Optics:** 4MP / 1080p Sony STARVIS CMOS sensors with $6\text{ mm} - 12\text{ mm}$ motorized varifocal lens.
- **Shutter Speed:** Enforce minimum shutter speed of $1/500\text{ s}$ to $1/1000\text{ s}$ to eliminate vehicle motion blur.
- **Enclosures:** IP67 weather-rated housings with integrated sunshields and internal heating/defogging elements.

### 3.2 Gate-Specific Environmental Calibration
1. **PEC Gate 1 (Main Entrance - Sector 12):**
   - High-throughput 4-lane entrance/exit with speed bumps.
   - Configure camera Wide Dynamic Range (WDR $\ge 120\text{ dB}$) to counteract blinding morning sunrise glare (08:30–10:00).
   - Configure lane mask polygon zones in [config/frigate/config.yml](file:///home/kirat/coding/honours/config/frigate/config.yml) to segment inbound vs outbound lanes.
2. **PEC Gate 2 (Hostel Entrance - Near Kalam & Shivalik Halls):**
   - High concentration of two-wheelers, bicycles, and courier riders (Zomato, Swiggy, Blinkit).
   - Install narrow-angle auxiliary $850\text{ nm}$ infrared floodlights to illuminate dirty or grease-stained motorcycle rear plates.
   - Fine-tune character segmentation on compact motorcycle plates ($200 \times 100\text{ mm}$ vs standard $500 \times 120\text{ mm}$ car plates).
3. **PEC Gate 3 (Faculty & Staff Residential Gate):**
   - Tree canopy causing dappled shadow glare during daytime.
   - Apply dynamic contrast normalization and background subtraction filtering to reject fluttering tree foliage.

### 3.3 Real-World Video Capture & Calibration Protocol
- Collect 500+ video clips (1,500–3,000 frames) across varied conditions:
  - Daytime clear (noon sun with harsh shadows).
  - Twilight / dusk (low contrast transitions).
  - Nighttime with high-beam glare and ambient sodium lighting.
  - Seasonal Chandigarh winter fog (December–January).
- Retrain YOLO11n with campus hard negatives (bumpers, stickers, headlights) to ensure false detections drop below $0.1\%$.

---

## 4. Tier 3: Barrier Controller & Hardware Interlock Integration

While the system's foundational mandate enforces human-in-the-loop operation, future phases include semi-automated assistance for verified residents. Physical barrier integration must adhere to strict hardware fail-safe architectures.

```
+----------------------------------------------------------------------------------------------------+
|                             BARRIER CONTROLLER HARDWARE INTERLOCK TOPOLOGY                         |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                                    CENTRAL FASTAPI DECISION ENGINE                                 |
|   Evaluates Observation -> Identifies Registered Resident -> Access State: ALLOWED                |
+----------------------------------------------------------------------------------------------------+
                                                  │ MQTT / Modbus TCP Command: `OPEN_PERMITTED`
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                              INDUSTRIAL BARRIER RELAY CONTROLLER (PLC)                             |
|   Hardware: ADAM-6060 / Moxa ioLogik / ESP32 Industrial Relay Board (DIN Rail Mounted)             |
+----------------------------------------------------------------------------------------------------+
                 │                                              │
                 │ Dry Contact Signal                           │ Interlock Check
                 ▼                                              ▼
+----------------------------------+          +----------------------------------+
|    INDUCTIVE GROUND SAFETY LOOP  |          |      MANUAL GUARD DEAD-MAN       |
|    Detects metal mass over lane  |          |    Pushbutton / Handheld Release |
+----------------------------------+          +----------------------------------+
                 │                                              │
                 └──────────────────────┬───────────────────────┘
                                        ▼
+----------------------------------------------------------------------------------------------------+
|                               BOOM BARRIER GATE MECHANISM (FAAC / CAME)                            |
|   Actuation Rule: [Software CLEAR] AND [Vehicle on Loop] AND [Guard Has Not Pressed E-STOP]        |
+----------------------------------------------------------------------------------------------------+
```

### 4.1 Industrial Controller Specifications & Protocol
- **Hardware Controller:** Industrial DIN-rail Ethernet relay board (Advantech ADAM-6060 or Moxa ioLogik E1214) with optically isolated digital inputs and dry-contact relay outputs.
- **Control Protocol:** Modbus TCP (Port 502) or authenticated MQTT (`campus/gates/GATE_1/actuate`).
- **Safety Interlock Matrix:**
  - **Condition 1 (Software Authorization):** Vehicle plate is verified in PostgreSQL with `status = ACTIVE` and `AccessState = ALLOWED`.
  - **Condition 2 (Vehicle Presence Loop):** Inductive road loop detector (`Loop 1`) confirms a physical vehicle is positioned directly in front of the gate barrier.
  - **Condition 3 (Emergency Stop Inactive):** Physical emergency mushroom stop button in the guard kiosk is normally closed (NC).
  - **Condition 4 (Guard Release):** In semi-automated mode, guard presses a physical authorization pedal or handheld button to confirm the clearance.

### 4.2 Hardware Barrier Sequence Flow

```mermaid
sequenceDiagram
    autonumber
    actor Driver as Resident Vehicle
    participant Loop as Inductive Ground Loop
    participant Cam as Lane ANPR Camera
    participant Server as FastAPI Access Engine
    participant PLC as ADAM-6060 Relay Controller
    participant Barrier as Physical Boom Barrier
    actor Guard as Human Security Guard

    Driver->>Loop: Vehicle rolls onto approach safety loop
    Loop->>PLC: Ground Loop Contact CLOSED (Presence Detected)
    Cam->>Server: Ingest Plate Read (PB65AB1234)
    Server->>Server: Evaluate Access Policy (Resident Faculty -> ALLOWED)
    Server->>PLC: Send Modbus Command (Pulse Relay 1, Duration: 500ms)
    PLC->>PLC: Check Safety Condition (Loop CLOSED && E-STOP Healthy)
    alt All Safety Conditions Met
        PLC->>Barrier: Trigger Barrier Raise Dry Contact
        Barrier->>Barrier: Motor raises boom arm to 90 degrees
        Driver->>Barrier: Vehicle transits through gate lane
        Driver->>Loop: Vehicle clears departure safety loop
        Loop->>Barrier: Trigger Automatic Close Limit Switch
        Barrier->>Barrier: Boom arm lowers safely
    else Loop Open or Emergency Stop Active
        PLC->>Server: Reject Command (Safety Interlock Active)
        Server->>Guard: Flash Warning Banner on Guard Console
        Guard->>Driver: Manual Inspection & Manual Gate Key
    end
```

---

## 5. Tier 4: Enterprise Production Hardening & Operational Deployment

### 5.1 TLS Reverse Proxy & Rate Limiting
- Deploy Nginx 1.26 as the TLS-terminating reverse proxy:
  ```nginx
  server {
      listen 443 ssl http2;
      server_name campus-gate.pec.edu.in;

      ssl_certificate /etc/letsencrypt/live/campus-gate.pec.edu.in/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/campus-gate.pec.edu.in/privkey.pem;
      ssl_protocols TLSv1.2 TLSv1.3;

      # Public courier intake rate limiting
      limit_req_zone $binary_remote_addr zone=intake_limit:10m rate=30r/m;
      location /intake {
          limit_req zone=intake_limit burst=10 nodelay;
          proxy_pass http://127.0.0.1:8000;
      }

      # Live SSE feed buffering bypass
      location /feed/stream {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Connection '';
          proxy_http_version 1.1;
          chunked_transfer_encoding off;
          proxy_buffering off;
          proxy_cache off;
      }

      location / {
          proxy_pass http://127.0.0.1:5173;
      }
  }
  ```

### 5.2 Meta WhatsApp Business Cloud API Integration
- Replace the local intake outbox provider ([backend/app/whatsapp/local.py](file:///home/kirat/coding/honours/backend/app/whatsapp/local.py)) with live Meta Cloud API:
  - Register Meta App under PEC organizational developer account.
  - Configure Webhook URL `https://campus-gate.pec.edu.in/webhooks/whatsapp`.
  - Validate webhook verification tokens (`hub.verify_token`) and signature validation (`X-Hub-Signature-256`).
  - Handle inbound invoice image attachments, download via Graph API v21.0, and dispatch to `DeliveryScreeningService`.

### 5.3 System Observability & Telemetry Monitoring
- **Prometheus Exporters:** Configure `/metrics` on FastAPI to expose:
  - `plate_recognition_latency_seconds` (histogram across p50, p95, p99).
  - `active_campus_vehicles_total` (gauge by category).
  - `mqtt_ingestion_queue_backlog` (gauge).
  - `camera_stream_fps` (gauge across Gate 1, Gate 2, Gate 3).
- **Grafana Dashboard:** Create perimeter security operations overview displaying real-time transit spikes, camera drops, and system resource utilization.
- **Sentry Integration:** Integrate Sentry Python SDK into FastAPI for unhandled exception capture and worker health tracing.

---

## 6. Prioritized Execution Checklist

```
[ ] STEP 1: Provision AWS EC2 g4dn.xlarge instance using research_track/hitl_anpr/aws/cloudformation.yaml.
[ ] STEP 2: Fine-tune Track A CCT OCR model with KERAS_BACKEND=torch on prepared/ocr_in_v1 to push accuracy > 85%.
[ ] STEP 3: Fine-tune Track B Qwen3-VL-2B on 1,000 multi-vendor QR delivery invoices and export GGUF/ONNX weights.
[ ] STEP 4: Collect and human-label 500+ real campus delivery line items at PEC Gate 2 for Track C calibration.
[ ] STEP 5: Conduct on-site camera angle and illumination survey at PEC Gate 1, Gate 2, Gate 3.
[ ] STEP 6: Mount physical cameras with IP67 enclosures and 850nm IR floodlights at Gate 1 and Gate 2.
[ ] STEP 7: Procure ADAM-6060 industrial Ethernet relay controller and bench-test Modbus TCP barrier actuation.
[ ] STEP 8: Connect live Meta WhatsApp Business Cloud API credentials to replace local intake provider.
[ ] STEP 9: Configure Nginx TLS 1.3 reverse proxy with Let's Encrypt certificates on campus-gate.pec.edu.in.
[ ] STEP 10: Deploy Prometheus and Grafana operational dashboards for system observability.
[ ] STEP 11: Execute 14-day shadow-mode pilot at PEC Gate 1 and audit guard override telemetry.
[ ] STEP 12: Finalize B.Tech Honors Thesis and research report with real campus benchmark metrics.
```
