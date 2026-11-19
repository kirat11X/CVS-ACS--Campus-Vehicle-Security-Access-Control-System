# Campus Gate ANPR & Vehicle Class Training Datasets Manifest (All 5 Solutions)

This manifest catalogs every dataset and pretrained checkpoint required to train and validate **all 5 Campus Gate ANPR solutions** (White Private, Yellow Commercial, Green EV, 2-Line 2W/3W Plates, Positional Grammar) plus the **Indian Vehicle Class Detector** (`car`, `two_wheeler`, `auto_rickshaw`, `bus`, `truck`).

---

## 1. Dataset & Checkpoint Inventory

| ID | Dataset / Checkpoint | Host & Canonical URL | License | Scale & Labels | Solution Role | Automated Method |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **DS-01** | **Indian License Plate Images (`umar1103/final-licence`)** | [Kaggle](https://www.kaggle.com/datasets/umar1103/final-licence) | CC BY 4.0 | 30,000 cropped Indian plate images (filename = exact plate string) | **Solution 2 & 4:** Primary Indian sequence OCR fine-tuning (`fast-plate-ocr` / CRNN) | `kaggle datasets download` |
| **DS-02** | **Awiros Indian ANPR-OCR (`Awiros/anpr-ocr`)** | [Hugging Face](https://huggingface.co/Awiros/anpr-ocr) | Apache-2.0 | 37.3M PP-OCRv5 weights (`model.safetensors`, `en_dict.txt`); 98.42% overall / 96.91% 2-row acc | **Solution 4:** Ready-to-run Indian 1-row & 2-row plate OCR baseline / seed | `huggingface_hub.snapshot_download` |
| **DS-03** | **Electric Vehicle Number Plate (`manu-mfyra/electric-vehicle-number-plate-bwvra`)** | [Roboflow Universe](https://universe.roboflow.com/manu-mfyra/electric-vehicle-number-plate-bwvra) | CC BY 4.0 | 162 annotated green EV plate images (YOLO boxes) | **Solution 1, 2 & 3:** Green EV (white/yellow text) Stage-1 detection & polarity test set | `roboflow` API / CLI (`ROBOFLOW_API_KEY`) |
| **DS-04** | **Indian Plate Detection (`ronakgohil/license-plate-dataset`)** | [Kaggle](https://www.kaggle.com/datasets/ronakgohil/license-plate-dataset) | OSS / Kaggle | 1,695 Indian vehicle images with YOLO plate bounding boxes | **Solution 2:** Stage-1 YOLO11n white/yellow plate detector fine-tuning | `kaggle datasets download` |
| **DS-05** | **Indian License Plates with Labels (`kedarsai/indian-license-plates-with-labels`)** | [Kaggle](https://www.kaggle.com/datasets/kedarsai/indian-license-plates-with-labels) | CC0-1.0 | 181 Indian vehicle images with XML/YOLO labels | **Solution 2:** Clean CC0 Stage-1 validation/training seed | `kaggle datasets download` |
| **DS-06** | **37-Class Plate & Character Dataset (`mohamedgobara/plate-license-recognition-dataset`)** | [Kaggle](https://www.kaggle.com/datasets/mohamedgobara/plate-license-recognition-dataset) | Kaggle | 37 classes (`0-9`, `A-Z`, `LicensePlate`) | **Solution 2:** 36-class character detector / glyph augmentation | `kaggle datasets download` |
| **DS-07** | **Indian Number Plate Dataset — NPDS (IURS)** | [Mendeley Data](https://data.mendeley.com/datasets/sxrnr7hwtk) | CC BY 4.0 | Augmented Indian plate bounding-box dataset (COCO/Roboflow) | **Solution 2:** Stage-1 Indian plate localization robustness (rotation/shear/noise) | Mendeley Data API / Browser |
| **DS-08** | **Indian Number Plate Character Dataset — ANPRINR (IURS)** | [Mendeley Data](https://data.mendeley.com/datasets/znghtgfnnf) | CC BY 4.0 | Augmented Indian character-level detection dataset (COCO/Roboflow) | **Solution 2:** Indian HSRP font character recognition (`0/O`, `1/I`, `B/8`) | Mendeley Data API / Browser |
| **DS-09** | **Dhaka Occluded Objects (South Asian Mixed Traffic)** | [Kaggle](https://www.kaggle.com/datasets/tanzimmostafa14/dhaka-occluded-objects-dataset/data) | Kaggle | 5,080 images (`car`, `motorcycle`, `cng`/auto-rickshaw, `bus`, `bicycle`, `person`) | **Vehicle Class Model:** Adds `auto_rickshaw` & `two_wheeler` alongside COCO | `kaggle datasets download` |
| **DS-10** | **DataCluster Labs Indian Number Plates & EV Plates** | Kaggle / Hugging Face (DataCluster Labs) | CC BY-NC-ND 4.0 (sample) / Commercial | 15,000+ HD full set (~200 free sample) + Indian green EV plates | **Solution 2:** Optional academic benchmark / EV supplement (check license terms) | Manual / Kaggle slug |
| **DS-11** | **PEC Campus Gate Calibration Set (To Capture Locally)** | Local `GATE_1`–`GATE_3` | Internal | 200–400 real gate frames (white cars, green EVs, 2W, autos, day/night) | **Solution 1–5:** Final domain adaptation (split by plate ID + `>5s` gaps) | `scripts/capture_gate_calibration_frames.py` |

---

## 2. Explicit Exclusions (Do NOT Download)
* **`minalchoudhary/india-ev-dataset` (Kaggle):** Tabular CSV for EDA only — contains **zero** vehicle or license plate images.
* **CCPD (Chinese Plates) for OCR:** Only suitable for generic bounding-box pretraining, never for Indian character/OCR training.

---

## 3. Required Credentials on Local Machine / AWS EC2
1. **Kaggle (`DS-01`, `DS-04`, `DS-05`, `DS-06`, `DS-09`):** Place `~/.kaggle/kaggle.json` (`chmod 600 ~/.kaggle/kaggle.json`) or set `KAGGLE_USERNAME` & `KAGGLE_KEY`.
2. **Hugging Face (`DS-02`):** Public download works without a token (`pip install huggingface_hub`); optionally set `HF_TOKEN` for faster rate limits.
3. **Roboflow (`DS-03`):** Set `ROBOFLOW_API_KEY` (`pip install roboflow`).
4. **Mendeley Data (`DS-07`, `DS-08`):** Direct public download via Mendeley Data REST API / browser links above.
