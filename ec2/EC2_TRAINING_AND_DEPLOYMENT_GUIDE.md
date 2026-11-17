# CVS-ACS: AWS EC2 GPU Training & Deployment Engineering Guide

**Target Deployment:** Punjab Engineering College (PEC), Sector 12, Chandigarh  
**System Architecture:** `OBSERVE -> ASSOCIATE -> CONTEXTUALIZE -> RECORD -> ALERT`  
**Purpose:** End-to-end operational guide for provisioning, fine-tuning, evaluating, and deploying the CVS-ACS computer vision and language model suite on AWS EC2 GPU instances (`g4dn.xlarge` / `g5.xlarge`).

---

## 1. Cloud Infrastructure & Instance Selection

Training vision-language models (Track B) and convolutional transformer OCR (Track A) requires dedicated GPU VRAM (>= 16 GB) and sustained compute that local edge machines often cannot provide.

### 1.1 Recommended Instance Types

| Instance Type | GPU / Accelerator | GPU VRAM | vCPUs | System RAM | On-Demand Cost | Spot Cost (Typical) | Best Fit For |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`g4dn.xlarge`** *(Recommended)* | 1x NVIDIA Tesla T4 | **16 GB** | 4 | 16 GB | ~$0.526 / hr | **~$0.158 / hr** *(70% savings)* | Track A OCR (CCT), Track C LLM QLoRA, Frigate + API testing |
| **`g5.xlarge`** | 1x NVIDIA A10G | **24 GB** | 4 | 16 GB | ~$1.006 / hr | **~$0.302 / hr** | Track B `Qwen3-VL-2B` fine-tuning (2x faster throughput) |
| **`g4dn.2xlarge`** | 1x NVIDIA Tesla T4 | **16 GB** | 8 | 32 GB | ~$0.752 / hr | **~$0.225 / hr** | Multi-worker parallel dataset ingestion + concurrent OCR training |

> [!TIP]
> **Cost Optimization with AWS Spot Instances:**  
> Use **Spot Instances** for all model training runs to achieve ~70% cost reduction. Because our training scripts (`ec2/train_track_a_ocr.sh`, `ec2/train_track_b_vlm.sh`, `ec2/train_track_c_llm.sh`) save incremental checkpoints, any spot interruption can be resumed seamlessly without losing progress.

### 1.2 AWS Free Tier & Promotional Credits
- **AWS Educate / AWS Activate / Student Credits:** Can provide between $300 and $1,000 in credits that fully offset EC2 GPU usage.
- **Service Quotas Request:** New AWS accounts default to `0` vCPUs for GPU instances. Before launching, request a quota increase in the AWS Console:
  1. Open **Service Quotas** > **Amazon Elastic Compute Cloud (Amazon EC2)**.
  2. Search for:
     - `Running On-Demand G and VT instances` (Quota code: `L-DB2E81BA`) -> Request **4 vCPUs**.
     - `All G and VT Spot Instance Requests` (Quota code: `L-3819AECD`) -> Request **4 or 8 vCPUs**.
  3. Approval typically completes within a few hours.

### 1.3 Recommended AMI & Storage
- **Base AMI:** `Ubuntu Server 22.04 LTS (HVM), SSD Volume Type` (64-bit x86) OR `Deep Learning OSS Nvidia Driver GPU AMI (Ubuntu 22.04)`.
- **EBS Volume:** Attach **100 GiB gp3** root volume (3,000 IOPS, 125 MB/s throughput). This provides ample headroom for datasets (30 GB cap), Docker images, and model checkpoints.

---

## 2. IAM Roles & Security Groups

### 2.1 IAM Instance Profile
Create an IAM Role (e.g. `CVS-ACS-EC2-GPU-Role`) attached to the EC2 instance with:
- `AmazonSSMManagedInstanceCore`: Enables browser-based terminal access via AWS Systems Manager Session Manager (no open port 22 required!).
- `AmazonS3FullAccess` *(Optional)*: For automated synchronization of weights to an S3 bucket (`s3://pec-cvs-acs-weights/`).

### 2.2 Security Group Rules (Firewall)
Configure the EC2 Security Group with the following inbound rules:

| Type | Port | Protocol | Source | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **SSH** | `22` | TCP | `Your_Public_IP/32` | Secure remote shell access |
| **Custom TCP** | `8000` | TCP | `Your_Public_IP/32` | FastAPI Backend API (`/docs`, `/metrics`) |
| **Custom TCP** | `5000` | TCP | `Your_Public_IP/32` | Frigate NVR Web Console |
| **Custom TCP** | `8554` | TCP | `Your_Public_IP/32` | RTSP / go2rtc Live Video Streams |
| **Custom TCP** | `1883` | TCP | `Your_Public_IP/32` | Mosquitto MQTT Broker |
| **Custom TCP** | `5173` | TCP | `Your_Public_IP/32` | Vite React Guard Dashboard |

> [!CAUTION]
> **Never open ports to `0.0.0.0/0` (Anywhere).** Restrict all inbound traffic strictly to your current IP address or use **SSH Tunneling** described below.

---

## 3. Zero-Exposure Access: Secure SSH Tunneling

Instead of opening ports 8000, 5000, and 5173 on the public internet, use an SSH tunnel to securely forward all web UIs directly to your local workstation's `localhost`:

```bash
# Execute this on your local machine:
ssh -i ~/.ssh/cvs-acs-key.pem \
    -N \
    -L 8000:localhost:8000 \
    -L 5000:localhost:5000 \
    -L 5173:localhost:5173 \
    -L 1883:localhost:1883 \
    ubuntu@<EC2_PUBLIC_DNS_OR_IP>
```

Once connected, open your local browser:
- **Guard Dashboard:** `http://localhost:5173`
- **FastAPI Documentation:** `http://localhost:8000/docs`
- **Frigate NVR UI:** `http://localhost:5000`

---

## 4. Turn-Key Setup & Automated Provisioning

Once connected to your EC2 instance via SSH:

### Step 1: Clone the CVS-ACS Repository
```bash
git clone https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System.git honours
cd honours
```

### Step 2: Run the Automated GPU Provisioning Script
The turn-key setup script automates the installation of NVIDIA Tesla drivers, CUDA 12.4, cuDNN 9, Docker with NVIDIA Container Toolkit, `uv`, Python 3.12, PyTorch, Transformers, PEFT, Keras 3 with `KERAS_BACKEND=torch`, and YOLO11.

```bash
chmod +x ec2/*.sh scripts/*.py
./ec2/setup_ec2_gpu.sh
```

### Step 3: Run the Healthcheck Diagnostic Suite
Verify that the GPU VRAM, CUDA runtime, and ML dependencies are operating with 100% health:

```bash
./ec2/ec2_healthcheck.sh
```
*Expected Output:*
```text
======================================================================
            CVS-ACS AWS EC2 SYSTEM & ML HEALTHCHECK           
======================================================================
1. GPU & CUDA ACCELERATION:
  [PASS] NVIDIA Driver: 550.90.07 | CUDA: 12.4
  [PASS] GPU Device:   Tesla T4
  [PASS] VRAM:         15109 MiB free / 15360 MiB total
  [PASS] Thermals:     38°C | Power: 26.14 W
...
==> EC2 GPU HOST IS FULLY CERTIFIED AND READY FOR ML TRAINING! <==
```

### Step 4: Download & Stage Datasets
Use the production dataset downloading utility to stage Track A, B, and C assets:

```bash
# Download and prepare all tracks:
python3 scripts/download_datasets.py --all

# Run verification check:
python3 scripts/download_datasets.py --verify
```

---

## 5. Launching Model Training Jobs

Always run long-running training jobs inside a persistent `tmux` session so network drops do not interrupt execution.

### 5.1 Track A: ANPR Second-Reader OCR (CCT Architecture)
Trains `cct_s_v2_global.keras` with `KERAS_BACKEND=torch` on the canonical `prepared/ocr_in_v1` dataset (13,698 crops):

```bash
# Start a detached tmux session:
tmux new -s train_ocr

# Launch Track A OCR training:
./ec2/train_track_a_ocr.sh --epochs 50 --batch-size 64

# (Optional: Quick smoke test to verify forward/backward pass):
./ec2/train_track_a_ocr.sh --smoke-test
```
- Detach from tmux: Press `Ctrl + B`, then press `D`.
- Re-attach anytime: `tmux attach -t train_ocr`.
- Output weights: `weights/track_a_ocr_cct.pt` and `weights/track_a_ocr_cct.onnx`.

### 5.2 Track B: Delivery Invoice Parsing (Qwen3-VL LoRA)
Fine-tunes `Qwen/Qwen3-VL-2B-Instruct` with 4-bit BitsAndBytes QLoRA on CORD-v2, Invoices Donut, and Indian GST invoices:

```bash
tmux new -s train_vlm
./ec2/train_track_b_vlm.sh --epochs 3 --batch-size 2 --grad-accum 8
```
- Output adapter: `weights/track_b_qwen3_vl_lora/`.

### 5.3 Track C: Prohibited Item Screening (Qwen3-1.7B LLM)
Trains and calibrates `Qwen/Qwen3-1.7B` on the canonical 320-item taxonomy with temperature scaling and safety gating:

```bash
tmux new -s train_llm
./ec2/train_track_c_llm.sh --epochs 6 --lr 2e-4
```
- Output adapter: `weights/track_c_qwen3_1.7b_lora/`.

### 5.4 Live GPU & Resource Monitoring
In a separate terminal or tmux pane, monitor GPU utilization in real time:
```bash
# Real-time graphical GPU monitor:
nvtop

# Or continuous nvidia-smi refresh:
watch -n 1 nvidia-smi
```

---

## 6. Synchronizing Weights Back to Campus Server

After training completes on EC2, copy the exported weights back to the local campus server or edge gateway:

### Option A: Direct rsync over SSH (Recommended)
Execute from your local campus server:
```bash
rsync -avhP \
    --partial \
    --append-verify \
    -e "ssh -i ~/.ssh/cvs-acs-key.pem" \
    ubuntu@<EC2_PUBLIC_IP>:~/coding/honours/weights/ \
    /home/kirat/coding/honours/weights/
```

### Option B: AWS S3 Bucket Backup
Execute on EC2:
```bash
aws s3 sync weights/ s3://pec-cvs-acs-weights/checkpoints/$(date +%Y%m%d)/
```
And retrieve on campus server:
```bash
aws s3 sync s3://pec-cvs-acs-weights/checkpoints/$(date +%Y%m%d)/ weights/
```

---

## 7. Full Production Deployment on EC2

To test the entire containerized CVS-ACS system on EC2 with GPU acceleration:

1. **Verify Docker GPU Pass-Through:**
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
   ```

2. **Launch Microservices Stack:**
   ```bash
   # Initialize environment configuration
   cp .env.example .env

   # Run Alembic migrations
   alembic upgrade head

   # Launch PostgreSQL, MQTT, Frigate NVR, FastAPI Backend, and Vite Frontend
   docker compose up -d
   ```

3. **Verify Service Health:**
   ```bash
   curl -s http://localhost:8000/health | jq .
   ```

4. **Shutdown when Done (Prevent Unnecessary Charges):**
   ```bash
   # From your local machine:
   aws ec2 stop-instances --instance-ids <YOUR_INSTANCE_ID>
   ```

---
*Document Version: 1.0.0 | Updated: 2026-11-16 | CVS-ACS Data & Compute Engineering Suite*
