# DATASETS AND MODELS CATALOG
## Campus Vehicle Security & Access-Control System (CVS-ACS)
### Exhaustive Catalog of Datasets, Pretrained Checkpoints, Fine-Tuned Weights, Canonical Taxonomies, and Licensing

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Target Deployment Site:** Punjab Engineering College (PEC), Sector 12, Chandigarh (`GATE_1`, `GATE_2`, `GATE_3`)  
**Scope:** Research Tracks A (ANPR), B (Invoices), C (Item Screening), and Campus Telemetry  
**Canonical Seed Taxonomy Count:** **Exactly 320 items** (8 classes, 191 brand/template families)

---

## 1. Executive Summary & Catalog Overview

The machine learning architecture of CVS-ACS combines lightweight edge computer vision models running locally on gate hardware with centralized transformer models handling invoice parsing and institutional policy screening.

```
+-----------------------------------------------------------------------------------------------+
|                                    CVS-ACS MACHINE LEARNING STACK                             |
+------------------------------------+--------------------------+-------------------------------+
| Track / Domain                     | Primary Model Class      | Current Artifact / Weights    |
+------------------------------------+--------------------------+-------------------------------+
| Track A: Plate Detection           | Ultralytics YOLO11n      | weights/yolo11n_plate_detector_finetuned.pt
| Track A: Plate Recognition (OCR)   | PyTorch CRNN (CNN+BiLSTM)| weights/indian_plate_crnn_best.pt / ONNX
| Track A: Cloud OCR Target          | Compact Conv Transformer | cct_s_v2_global.keras (KERAS_BACKEND=torch)
| Track B: Document Invoice OCR      | RapidOCR + Tesseract 5.5 | In-process Python wrappers    |
| Track B: Cloud Invoice VLM         | Qwen3-VL-2B-Instruct     | Staged HuggingFace weights (4.0 GB)
| Track C: Item Screening LLM        | Qwen3-1.7B + 4-bit QLoRA | research_track/finetune/models/full_c_v1
| Track C: Semantic Embedding Baseline| MiniLM-L12-v2            | paraphrase-multilingual-MiniLM-L12-v2 (477 MB)
+------------------------------------+--------------------------+-------------------------------+
```

---

## 2. Track A Datasets: Indian License Plates & Vehicle Tracking

Track A focuses on vehicle detection, license plate localization, character segmentation, and optical character recognition adapted to Indian statutory font standards and road conditions.

### 2.1 Catalog of Indian License Plate Datasets

| Dataset Identifier | Source / Reference | Size / Count | Splits (Train/Val/Test) | License | Role & Acquisition Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`kedarsai/indian-license-plates`** | [Kaggle Dataset](https://www.kaggle.com/datasets/kedarsai/indian-license-plates-with-labels) | 181 annotated images | 181 full images | CC0-1.0 (Public Domain) | **Downloaded & Used** in initial YOLO11n training. |
| **`prepared/plate_det_in_v1`** | Combined 22 Kaggle + 6 Roboflow sets | 1,716 verified images | 1,483 train / 115 val / 118 test | Mixed OSS / CC BY 4.0 | **Compiled & Used** for YOLO11n base training run. |
| **`unified_plate_dataset`** | Unified campus & synthetic plate set | 3,598 images | 3,061 train / 537 val | Internal / Permissive | **Compiled & Used** in extended 100-epoch YOLO11n training. |
| **`prepared/ocr_in_v1`** | Avinash-6 + KP00011 curated crops | 13,698 real plate crops | 9,570 train / 2,053 val / 2,073 test | Apache-2.0 / MIT | **Built & Verified**; zero plate-text overlap between splits. |
| **`training_1/ocr_dataset`** | Statutory high-res Indian plate crops | 1,081 verified crops | 881 train / 200 val | Internal / Permissive | **Compiled & Used** in CRNN OCR extended training. |
| **`DataCluster Indian Plates`** | [HuggingFace DataCluster](https://huggingface.co/datasets/DataCluster) | 15,000+ images (5,000 annotated)| Sample subset available | CC BY-NC-ND / Custom | **Evaluated**; sample subset used for validation; commercial license withheld. |
| **`sanchit2843/Indian_LPR`** | [GitHub / arXiv:2111.06054](https://github.com/sanchit2843/Indian_LPR) | 16,192 images (2.5 MB metadata)| Withheld by original authors | Research Only | **Metadata Downloaded**; raw frames withheld by authors. |
| **`IND-VNP` / IEEE DataPort** | IEEE DataPort / arXiv:2207.06657 | 3,000+ multi-state plates | Diverse Indian states | Academic / Restricted | **Cataloged** as fallback if local footage needs augmentation. |
| **`PEC Campus Gate Footage`** | On-site cameras at Gates 1, 2, 3 | Target: 1,500–3,000 frames | Day, Night, Twilight, Rain | Institutional / Consented | **In Progress**; mandatory for production site calibration. |

### 2.2 Supplemental Vehicle Re-ID & Traffic Benchmarks

| Benchmark / Dataset | Provider / Reference | Scale / Annotation | License | Application in CVS-ACS |
| :--- | :--- | :--- | :--- | :--- |
| **`BDD100K`** | UC Berkeley AI Research | 100,000 driving frames | BSD 3-Clause | Pretraining vehicle detection backbones across weather conditions. |
| **`UA-DETRAC`** | IEEE Transactions on PAMI | 100,000 traffic frames | CC BY 4.0 | Multi-vehicle tracking and cross-lane movement verification. |
| **`VeRi-776`** | Tsinghua University | 776 vehicles, 50,000 images | Research Use Only | Cross-camera vehicle Re-Identification between Gate 1 and Gate 2. |
| **`UFPR-ALPR`** | Federal University of Paraná | 4,500 ALPR images | Research Use Only | Baseline comparison for non-Indian plate detection algorithms. |
| **`CCPD`** | Chinese City Parking Dataset | 250,000 plate images | Research Use Only | Generic bounding box detector pretraining only (NOT for Indian text). |

---

## 3. Track B Datasets: Invoices, Receipts & Financial Documents

Track B processes unstructured digital and paper food delivery invoices, receipts, and order intake slips.

### 3.1 Catalog of Document & Invoice Datasets

| Dataset Identifier | Source / Publisher | Volume / Format | License | Status & Utilization Plan |
| :--- | :--- | :--- | :--- | :--- |
| **`invoices-donut-data-v1`** | [HuggingFace: katanaml-org](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) | 500 annotated invoices (189 MB) | MIT License | **Downloaded** to `~/ml-assets/campus/`; ready for VLM evaluation. |
| **`cord-v2`** | [HuggingFace: naver-clova-ix](https://huggingface.co/datasets/naver-clova-ix/cord-v2) | ~1,000 receipts (2.2 GB) | CC BY 4.0 | **Downloaded** to `~/ml-assets/campus/`; primary VLM fine-tuning set. |
| **`Divya52 Indian GST Invoices`**| HuggingFace: Divya52 | ~2,000 synthetic Indian GST bills | CC BY 4.0 | **Cataloged**; contains Hindi, Kannada, and English tax layouts. |
| **`SROIE 2019`** | ICDAR 2019 Challenge | 973 receipt images + annotations | CC BY 4.0 | General OCR line-item and total extraction benchmark. |
| **`FUNSD`** | Form Understanding in Noisy Scans| 200 scanned document forms | CC BY 4.0 | LayoutLM spatial bounding box pretraining. |
| **`RVL-CDIP` / `IIT-CDIP`** | Scanning & Document Analysis Lab | 400,000 grayscale documents | Research / Open | Corpus pretraining for deep document layout analysis. |
| **`Track B Synthetic Fixtures`**| Internal Test Harness | 32 documents + 6 adversarial cases | Internal | **Evaluated**; achieved 100% schema pass and 87.5% math pass. |
| **`Consented Real Invoices`** | Campus Food Delivery Collection | Target: 100+ Zomato/Swiggy orders | Consented / Internal | **In Collection**; required before production VLM sign-off. |

---

## 4. Track C Datasets: Item Taxonomy & Security Classification

Track C maps extracted delivery line items into institutional security categories, identifying contraband and regulatory violations.

### 4.1 Canonical Item Taxonomy Dataset (`item_taxonomy_seed.csv`)
- **Canonical Storage Location:** `research_track/track_c/fixtures/item_taxonomy_seed.csv`
- **Total Verified Rows:** **Exactly 320 items** (300 standard synthetic quick-commerce items + 20 UNKNOWN edge cases).
- **Brand / Family Diversity:** 191 unique brand and packaging template families.
- **Class Distribution & Verdict Policy:**

| Category Identifier | Class Description | Item Count | Deterministic Policy Verdict | Canonical Reason Code |
| :--- | :--- | :--- | :--- | :--- |
| `NORMAL` | Everyday snacks, cooked meals, bakery, dairy, stationery | 140 | `ALLOW` | `FOOD_OK` / `STATIONERY_OK` |
| `TOBACCO_NICOTINE` | Cigarettes, bidi, gutkha, vape pods, rolling papers | 30 | `ALERT` | `TOBACCO_RESTRICTED` |
| `ALCOHOL` | Beers, whiskey, rum, vodka, RTD alcoholic beverages | 30 | `ALERT` | `ALCOHOL_RESTRICTED` |
| `OTC_MEDICINE` | Pain relief tablets, antacids, bandages, cough lozenges | 30 | `REVIEW` | `MEDICINE_NEEDS_APPROVAL` |
| `RX_SCHEDULED_DRUG` | Prescription sleeping pills, injectables, scheduled drugs | 25 | `ALERT` | `HAZMAT_NEEDS_APPROVAL` |
| `HAZARDOUS_CHEMICAL` | Lab acids, acetone, kerosene, fireworks, toxic solvents | 25 | `ALERT` | `HAZMAT_NEEDS_APPROVAL` |
| `SHARP_OBJECT` | Utility blades, box cutters, tactical knives, machetes | 20 | `ALERT` | `WEAPON_RESTRICTED` |
| `UNKNOWN` | Severe OCR corruptions, Hinglish slang, untranslated terms| 20 | `REVIEW` | `UNKNOWN_CATEGORY` |
| **TOTAL** | **Canonical Seed Item Taxonomy** | **320** | — | — |

### 4.2 Training Split Protocol (`research_track/finetune/scripts/c_split.py`)
- **Train Partition:** 188 rows (58.8%) across 114 brand families.
- **Validation Partition:** 69 rows (21.5%) across 42 brand families.
- **Held-Out Test Partition:** 63 rows (19.7%) across 35 brand families.
- **Partitioning Invariant:** Grouped by brand family to guarantee zero data leakage between training and evaluation splits.

---

## 5. Model Checkpoints & Pretrained Weights Catalog

### 5.1 Track A: License Plate Detectors & OCR Encoders

```
weights/
├── yolo11n_plate_detector_best.pt         # Ultralytics PyTorch weights (5.4 MB, 100 epochs, mAP50=0.9455)
├── yolo11n_plate_detector_best.onnx       # Optimized ONNX export for edge inference (10.6 MB)
├── yolo11n_plate_detector_finetuned.pt    # Video-retrained PyTorch weights (5.4 MB, mAP50=0.8396)
├── yolo11n_plate_detector_finetuned.onnx  # Video-retrained ONNX export (10.6 MB)
├── yolo11n_plate_detector_fleet_best.pt   # Fleet-optimized PyTorch weights (5.4 MB, mAP50=0.8406)
├── yolo11n_plate_detector_fleet_best.onnx # Fleet-optimized ONNX export (10.6 MB)
├── indian_plate_crnn_best.pt              # PyTorch CRNN OCR weights (34.9 MB, 120 epochs, Acc=63.12%, CER=8.51%)
├── indian_plate_crnn_best.onnx            # ONNX export of PyTorch CRNN OCR (34.8 MB)
├── yolov9-256-license-plates.onnx         # Legacy YOLOv9 baseline checkpoint (7.8 MB)
└── cpu_model.tflite                       # Quantized mobile TFLite model (4.3 MB)
```

#### Detailed Model Specifications:
1. **Ultralytics YOLO11n Plate Detector:**
   - *Architecture:* Ultralytics YOLO11 nano (2.6M parameters).
   - *Input Resolution:* $640 \times 640 \times 3$.
   - *Export Targets:* PyTorch FP32 (`.pt`), ONNX Runtime (`.onnx`), OpenVINO.
   - *Training Hardware:* NVIDIA GeForce RTX 4050 Laptop GPU (17 min base / 12.5 min finetuned).
   - *Performance:* 0.9455 val mAP50, 0.6718 val mAP50-95, 0.9207 Precision, 0.9038 Recall.
2. **PyTorch CRNN License Plate OCR:**
   - *Architecture:* 7-layer CNN Feature Extractor + 2-layer Bidirectional LSTM Sequence Encoder + CTC Loss.
   - *Input Resolution:* $(B, 3, 32, 128)$.
   - *Vocabulary:* 36 Alphanumeric Characters (`0-9`, `A-Z`) + CTC Blank token (`0`).
   - *Performance:* 63.12% Exact Plate Accuracy, 8.51% Character Error Rate over 120 epochs.
3. **Compact Convolutional Transformer (`cct_s_v2_global.keras`):**
   - *Architecture:* CCT-Small v2 with Sequence Pooling (11 slots, vocabulary `0-9A-Z_`).
   - *License:* MIT License.
   - *Zero-Shot Baseline:* 69.5% statutory format-valid string generation on IN-02 crops.
   - *Status:* Target for cloud fine-tuning on AWS EC2 with `KERAS_BACKEND=torch`.
4. **MobileViT-v2 (`fast-plate-ocr`):**
   - *Architecture:* MobileViT-v2 backbone with lightweight CTC decoder.
   - *Format:* ONNX Runtime export (`fast-plate-ocr-mobilevit-v2.onnx`).
   - *Inference Latency:* $\sim 18\text{ ms}$ on Intel Core i7-13650HX CPU.
5. **PaddleOCR-VL (0.9B):**
   - *Architecture:* Multimodal Vision-Language OCR model (0.9B parameters).
   - *Requirements:* Staged locally (`2.0 GB`); requires isolated Python 3.12 virtualenv.

---

### 5.2 Track B: Document Parsers & Vision-Language Models

1. **RapidOCR (PP-OCRv4 ONNX):**
   - *Role:* Primary local in-process invoice text extraction engine (`backend/app/services/invoice_reader.py`).
   - *License:* Apache-2.0.
   - *Configuration:* Tuned with text threshold `RAPIDOCR_TEXT_SCORE=0.30` to prevent loss of small numerical quantity digits.
2. **Tesseract OCR (5.5.3 Native Binary):**
   - *Role:* Secondary fallback OCR engine when RapidOCR yields no bounding fragments.
   - *License:* Apache-2.0.
   - *Invocation:* Python wrapper via `pytesseract 0.3.13`.
3. **Qwen3-VL-2B-Instruct:**
   - *Publisher:* Alibaba Cloud / Qwen Team ([HuggingFace Repo](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)).
   - *Parameters:* 2 Billion parameters (multimodal vision + text decoder).
   - *License:* Apache-2.0.
   - *Local Staging:* Staged under `~/ml-assets/campus/models/Qwen3-VL-2B-Instruct` (4.0 GB weights + 23 MB LoRA adapter).
   - *Compute Requirement:* Requires $\ge 16\text{ GB}$ VRAM; target for AWS EC2 `g4dn.xlarge` fine-tuning.
4. **LayoutLMv3 & PP-StructureV3:**
   - *Role:* Specialized spatial document transformer models cataloged for complex multi-column invoice parsing.

---

### 5.3 Track C: Policy Classifiers & Language Models

1. **Qwen3-1.7B + `full_c_v1` QLoRA:**
   - *Base Model:* `Qwen/Qwen3-1.7B` (Alibaba Cloud, 1.7B parameters, Apache-2.0).
   - *Fine-Tuning Method:* 4-bit NormalFloat QLoRA ($r=16, \alpha=32$, target modules `q_proj`, `k_proj`, `v_proj`, `o_proj`).
   - *Storage Location:* `research_track/finetune/models/full_c_v1/`.
   - *Trained Artifact Size:* 16.8 MB LoRA adapter weights (`adapter_model.safetensors`).
   - *Benchmark Metrics:* **0.841 Accuracy**, **0.818 Macro-F1**, **0.0% Invalid JSON** on held-out test split ($n=63$).
2. **Paraphrase-Multilingual-MiniLM-L12-v2:**
   - *Publisher:* Sentence-Transformers / HuggingFace.
   - *Parameters:* 118 Million parameters (dense 384-dimensional vector embeddings).
   - *License:* Apache-2.0.
   - *Local Staging:* Staged under `~/ml-assets/campus/models/paraphrase-multilingual-MiniLM-L12-v2` (477 MB).
   - *Performance:* Evaluated as k-NN semantic classifier baseline (0.540 Accuracy, 0.406 Macro-F1).

---

## 6. Storage Locations, Checksums & Disk Allocation

To comply with the project's strict 30 GB local disk cap on ML assets, models and datasets are allocated across designated partitions:

```
Directory Path                                Size      Allocation Description
------------------------------------------------------------------------------------------
/home/kirat/coding/honours/weights/           130 MB    Production PyTorch & ONNX checkpoints
/home/kirat/coding/honours/training_1/        850 MB    Local training runs & dataset archives
/home/kirat/ml-assets/campus/datasets/        8.4 GB    Raw & prepared plate / invoice datasets
/home/kirat/ml-assets/campus/models/          6.5 GB    Staged HuggingFace pretrained backbones
/home/kirat/coding/honours/runs/              88 MB     YOLO & CRNN training logs & metrics
------------------------------------------------------------------------------------------
TOTAL ML ASSETS ALLOCATION:                   15.97 GB  (Well under 30.0 GB cap)
```

---

## 7. Dataset & Model Compliance and Licensing Summary

All datasets and models integrated into CVS-ACS satisfy open-source research and academic licensing requirements:

1. **Permissive Open Source (MIT, Apache-2.0, CC0-1.0):**
   - `kedarsai/indian-license-plates` (CC0-1.0)
   - `prepared/ocr_in_v1` (Apache-2.0 / MIT)
   - `invoices-donut-data-v1` (MIT)
   - `Qwen3-1.7B` and `Qwen3-VL-2B-Instruct` (Apache-2.0)
   - `RapidOCR` and `Tesseract` (Apache-2.0)
2. **Attribution Creative Commons (CC BY 4.0):**
   - `cord-v2` (CC BY 4.0)
   - `Divya52 Indian GST Invoices` (CC BY 4.0)
   - `SROIE 2019` and `FUNSD` (CC BY 4.0)
3. **Internal Institutional / Consented Data:**
   - `item_taxonomy_seed.csv` (320 items, Internal Academic Thesis)
   - Synthetic invoice fixtures (38 documents, Internal)
   - PEC campus gate video captures (Consented Institutional CCTV)
4. **Prohibited / Withheld Data:**
   - Proprietary or unconsented student personal ID photos are strictly prohibited from collection.
   - Face recognition datasets are strictly banned under institutional privacy invariants.
