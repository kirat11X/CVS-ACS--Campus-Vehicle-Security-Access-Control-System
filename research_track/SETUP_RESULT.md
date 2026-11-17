# Isolated ML Research Track: Setup & Staging Report

**Punjab Engineering College (PEC), Chandigarh**  
**Campus Vehicle Security & Access-Control System**  
**Staging Directory:** `/home/kirat/coding/honours/research_track/`  
**Heavy Assets Directory:** `~/ml-assets/campus/`

---

## 1. Executive Summary

An isolated, non-intrusive machine learning staging track has been successfully prepared for the Campus Vehicle Security & Access-Control System. 

### Hard Rules Compliance
1. **No Project Disruption:** Zero docker/docker compose, uvicorn, alembic, pytest, or dev server processes were run against production services. All localhost ports (5433, 1883, 5000, 5678, 8000, 3000) remain untouched.
2. **Zero In-Place Modifications:** `git diff --stat` across the repository is strictly empty (`0 files changed`). Existing production files (`README.md`, `context.md`, `PROJECT_ARCHITECTURE.md`, `SETUP_REPORT.md`, `alembic/`, `backend/`, `docker-compose.yml`, `.env`, `.venv/`) were preserved without modification.
3. **Dedicated Python 3.12 Runtime:** All ML packages reside in an isolated virtual environment at `~/ml-assets/campus/.venv-ml` (Python 3.12.11) managed via `uv`, preserving the production Python 3.14 environment.
4. **Zero GPU Execution:** No model weights were loaded into memory, no inference executed, and no CUDA kernels dispatched. The RTX 4050 Laptop GPU remains completely idle and free for ongoing concurrent sessions.
5. **System Integrity:** No sudo commands or global package modifications were executed.

---

## 2. Storage & Disk Budget Accounting

Per task constraints, disk capacity was inspected prior to download and capped strictly at 30 GB total assets.

* **Disk Available Before Task:** 101 GiB available (449 GiB total partition, 78% utilized).
* **Disk Available After Staging:** 86 GiB available (81% utilized).
* **Safety Floor:** Well above the 40 GiB safety floor (+46 GiB headroom).
* **Total Assets Staged:** 22 GiB in `~/ml-assets/campus/` (compliant with the 30 GB ceiling).
* **Hugging Face Cache Isolation:** `HF_HOME=~/ml-assets/campus/hf` configured to prevent redundant caching in user home directory.

---

## 3. Staged Assets Summary

### A. Machine Learning Models (`~/ml-assets/campus/models/`)

| Asset Name | Files Staged | Size | License | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **YOLOv9 Plate Detectors** | 3 ONNX models (`384`, `640`, `608`) | 44.2 MB | Apache-2.0 | **DOWNLOADED** | First-stage ANPR vehicle plate localization. |
| **fast-plate-ocr MobileViT-v2** | ONNX weights + config YAML | 5.0 MB | Apache-2.0 | **DOWNLOADED** | Character recognition baseline for Indian HSRP fine-tuning. |
| **PaddleOCR-VL (0.9B)** | `model.safetensors` + tokenizer + configs | 2.0 GB | Apache-2.0 | **DOWNLOADED** | Second-reader visual language OCR for degraded plates. |
| **paraphrase-multilingual-MiniLM-L12-v2** | `model.safetensors` + tokenizer + configs | 477 MB | Apache-2.0 | **DOWNLOADED** | Semantic embedding resolution against registry tokens. |
| **Qwen3-VL-2B Receipt LoRA** | `adapter_model.safetensors` + configs | 23 MB | Apache-2.0 | **DOWNLOADED** | Vision-language adapter for quick-commerce receipt keys. |
| **chai1me Qwen2-VL Receipt LoRA** | Architecture card + configs | 18 KB | Apache-2.0 | **DOWNLOADED** | Model card only (no weights per spec). |
| **saliousk Qwen2-VL CORD LoRA** | Architecture card + configs | 22 KB | Apache-2.0 | **DOWNLOADED** | Model card only (no weights per spec). |
| **Qwen3-1.7B** | Safetensors shards (3.8 GB) + tokenizer | 3.8 GB | Apache-2.0 | **DOWNLOADED** | Base classifier for zero-shot security screening. |
| **Qwen3-VL-2B-Instruct** | `model.safetensors` (4.0 GB) + configs | 4.0 GB | Apache-2.0 | **DOWNLOADED** | Base VLM for full invoice table parsing. |
| **Qwen2.5-VL-3B-Instruct** | None | 7.52 GB | Qwen Research | **SKIPPED** | Tier 2 candidate skipped to respect 30 GB asset budget. |

### B. Datasets (`~/ml-assets/campus/datasets/` & `research_track/datasets/`)

| Dataset Name | Scope / Content | Size | License | Status | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Item Taxonomy Seed** | 300 unique synthetic lines (7 categories) | 14 KB | Project Internal | **DOWNLOADED / CREATED** | High-diversity quick-commerce abbreviations, Hinglish, groceries. |
| **invoices-donut-data-v1** | Train, validation, test Parquet files | 189 MB | MIT | **DOWNLOADED** | Complete invoice document ground truth sequences. |
| **cord-v2** | Consolidated receipt dataset Parquets (2.2 GB) | 2.2 GB | CC-BY-4.0 | **DOWNLOADED** | Hierarchical food and retail receipts (all 4 train shards, val, test complete). |
| **Indian_LPR (arXiv 2111.06054)** | Cloned GitHub repository & pipeline code | 2.5 MB | Research Only | **MANUAL** | Raw 16,192 images withheld by authors; code staged. |
| **arXiv 2207.06657 E2E ANPR** | Research paper review & dataset link analysis | — | CC-BY-4.0 | **MANUAL** | No public URL published; requires author correspondence. |
| **Kaggle Indian Plates with Labels** | `kedarsai/indian-license-plates-with-labels` | — | Community Data | **MANUAL** | Missing `~/.kaggle/kaggle.json`; exact steps below. |
| **IEEE DataPort Indian LPR** | Indian LPR benchmark dataset | — | IEEE Terms | **MANUAL** | Requires IEEE account login; exact steps below. |
| **IEEE DataPort IND-VNP** | Indian vehicle number plate dataset | — | IEEE Terms | **MANUAL** | Requires IEEE account login; exact steps below. |

---

## 4. Manual Datasets: Exact Retrieval Steps

### 1. Kaggle: Indian License Plates with Labels (`kedarsai/indian-license-plates-with-labels`)
* **Prerequisite:** Kaggle account API token.
* **Steps:**
  1. Go to [kaggle.com/settings](https://www.kaggle.com/settings) and click **Create New Token**.
  2. Save the downloaded `kaggle.json` to `~/.kaggle/kaggle.json` and restrict permissions:
     ```bash
     chmod 600 ~/.kaggle/kaggle.json
     ```
  3. Download and extract the dataset using the virtual environment:
     ```bash
     ~/ml-assets/campus/.venv-ml/bin/kaggle datasets download \
       -d kedarsai/indian-license-plates-with-labels \
       -p ~/ml-assets/campus/datasets/kaggle-indian-license-plates \
       --unzip
     ```

### 2. IEEE DataPort: Indian License Plate Datasets & IND-VNP
* **Prerequisite:** IEEE member or institutional login.
* **Steps:**
  1. Open [ieeedataport.org](https://ieeedataport.org/) in a web browser and sign in.
  2. Search for `Indian License Plate Recognition Dataset (YOLO & OCR)` and `IND-VNP`.
  3. Click **Download Dataset** and accept the non-commercial academic data license.
  4. Move and unpack the archive:
     ```bash
     mkdir -p ~/ml-assets/campus/datasets/ieee-dataport-indian-lpr
     unzip ~/Downloads/<dataset-file>.zip -d ~/ml-assets/campus/datasets/ieee-dataport-indian-lpr/
     ```

### 3. Indian_LPR (arXiv 2111.06054)
* **Status:** The repository code is cloned at `~/ml-assets/campus/code/Indian_LPR`.
* **Author Note:** The authors stated in the repository README that road image data cannot be released publicly under current Indian motor vehicle privacy guidelines. For synthetic augmentation or training, use the Kaggle `kedarsai` dataset or contact `sanchit2843` directly for academic data sharing agreements.

---

## 5. Environment & Software Verification

* **Python Virtual Environment:** `~/ml-assets/campus/.venv-ml` (Python 3.12.11)
* **Dependency Health (`uv pip check`):**
  ```text
  Checked 177 packages in 1ms
  All installed packages are compatible
  ```
* **Dependency Pinning:** 177 exact versions frozen to `research_track/requirements-ml.txt`.
* **Unsloth Installation:** Successfully installed `unsloth==2026.10.3` and `unsloth-zoo==2026.10.3`.
* **Frontend Verification:**
  - `research_track/frontend/` initialized with React 19, TypeScript 5.8, Tailwind CSS, and Vite 6.
  - Resolved `ImportMeta.env` types via `src/vite-env.d.ts`.
  - Executed `npm run build`: Type-check passed with 0 errors; built production bundle in 915ms.

---

## 6. How to Resume Background Downloads

All Hugging Face downloads are configured to be fully idempotent and resumable using HTTP range requests and local lockfiles:

```bash
# 1. Set environment variables
export HF_HOME="$HOME/ml-assets/campus/hf"
export HF_HUB_ENABLE_HF_TRANSFER=1  # Fast Rust downloads

# 2. Resume Qwen3-1.7B
~/ml-assets/campus/.venv-ml/bin/hf download Qwen/Qwen3-1.7B \
  --local-dir ~/ml-assets/campus/models/Qwen3-1.7B

# 3. Resume Qwen3-VL-2B-Instruct
~/ml-assets/campus/.venv-ml/bin/hf download Qwen/Qwen3-VL-2B-Instruct \
  --local-dir ~/ml-assets/campus/models/Qwen3-VL-2B-Instruct

# 4. Resume CORD-v2 Dataset
~/ml-assets/campus/.venv-ml/bin/hf download naver-clova-ix/cord-v2 \
  --repo-type dataset \
  --local-dir ~/ml-assets/campus/datasets/cord-v2
```

---

## 7. Artifacts Index in `research_track/`

* `PROJECT_DIGEST.md`: Concise 54-line architectural digest preserving the 10 invariants.
* `PROPOSED_CONTEXT_CHANGES.md`: Explicit staging exception protecting production `context.md`.
* `requirements-ml.txt`: Pinned Python 3.12 ML environment specifications (177 packages).
* `MANIFEST.yaml`: Machine-readable asset catalog with licenses and SHA256 checksums.
* `LINKS.md`: Cross-referenced resource catalog organized across Tracks A, B, and C.
* `datasets/item_taxonomy_seed/seed_items.csv`: 320 canonical synthetic line items across 8 categories.
* `db_draft/`: Staging DDL, Alembic migration draft, SQLAlchemy 2.0 models, and seed policy JSON.
* `frontend/`: React + Vite + TypeScript dashboard scaffold with 5 pages and mock data.
* `ec2/`: Provisioning templates (`bootstrap.sh`, `sync_assets.sh`) for AWS g4dn.xlarge instances.
