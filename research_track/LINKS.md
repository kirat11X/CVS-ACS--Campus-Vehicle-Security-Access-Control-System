# Machine Learning Research Track: Resource Links & Repositories

This document catalogs all machine learning models, public datasets, research papers, and software repositories evaluated and staged for the **Campus Vehicle Security & Access-Control System** at Punjab Engineering College (PEC), Chandigarh.

The research assets are categorized across the three core operational pipelines:
- **Track A:** Indian ANPR Second-Reader OCR & Registry-Constrained Fuzzy Resolution (Perimeter Gate Cameras)
- **Track B:** Delivery Invoice Line-Item Extraction (WhatsApp Ingestion Pipeline)
- **Track C:** Prohibited Item Categorization & Policy Rules Engine (Deterministic Access Review)

---

## Track A: Indian ANPR Perception & Second-Reader OCR

| Asset Name | Type | Source URL / Repository | License | Purpose in System |
| :--- | :--- | :--- | :--- | :--- |
| **YOLOv9 License Plate Detectors** | Model (ONNX) | [ankandrew/open-image-models Releases](https://github.com/ankandrew/open-image-models/releases) | Apache-2.0 | First-stage bounding box localization for vehicle license plates at Gates 1–3 (`yolo-v9-t-384`, `yolo-v9-t-640`, `yolo-v9-s-608`). |
| **fast-plate-ocr (MobileViT-v2)** | Model & Code | [ankandrew/fast-plate-ocr](https://github.com/ankandrew/fast-plate-ocr) | Apache-2.0 | Lightweight character recognition backbone used as fine-tuning initialization for Indian high-security registration plates (HSRP). |
| **PaddleOCR-VL (0.9B)** | Model (Vision-Language) | [PaddlePaddle/PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | Apache-2.0 | Second-reader visual language OCR for degraded, multi-line, or non-standard vehicle number plates. |
| **Multilingual MiniLM (L12-v2)** | Model (Embeddings) | [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | Apache-2.0 | Semantic text similarity and typo-tolerant vector matching against campus vehicle registry. |
| **Indian_LPR (arXiv 2111.06054)** | Paper & Code | [sanchit2843/Indian_LPR](https://github.com/sanchit2843/Indian_LPR) / [arXiv:2111.06054](https://arxiv.org/abs/2111.06054) | Academic Research | Benchmark architecture with 4-point polygon plate localization and character segmentation in Indian driving conditions. |
| **E2E Indian ANPR (arXiv 2207.06657)** | Research Paper | [arXiv:2207.06657](https://arxiv.org/abs/2207.06657) | CC-BY-4.0 | Evaluation of end-to-end number plate recognition on diverse Indian vehicle datasets (1.5k sample evaluation). |
| **Indian License Plates with Labels** | Dataset | [Kaggle: kedarsai/indian-license-plates-with-labels](https://www.kaggle.com/datasets/kedarsai/indian-license-plates-with-labels) | Community Data | YOLOv5-formatted Indian vehicle images with annotated plate bounding boxes for detector transfer learning. |
| **IEEE DataPort Indian LPR & IND-VNP** | Dataset | [IEEE DataPort](https://ieeedataport.org/) | IEEE Terms (Login Required) | Benchmark datasets for Indian vehicle number plate OCR and character recognition under varied illumination. |

---

## Track B: Delivery Invoice Parsing & Line-Item Extraction

| Asset Name | Type | Source URL / Repository | License | Purpose in System |
| :--- | :--- | :--- | :--- | :--- |
| **Qwen3-VL-2B-Instruct** | Model (Multimodal VLM) | [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) | Apache-2.0 | Small-footprint multimodal vision-language model for parsing quick-commerce invoices (Swiggy Instamart, Zepto, Blinkit, Zomato). |
| **Qwen3-VL Receipt LoRA** | Model Adapter | [systemk-ai/Qwen3-VL-2B-Instruct-receipt-lora](https://huggingface.co/systemk-ai/Qwen3-VL-2B-Instruct-receipt-lora) | Apache-2.0 | Fine-tuned parameter-efficient LoRA adapter specializing in receipt and invoice structured key-value extraction. |
| **Qwen2.5-VL-3B-Instruct** | Model (Multimodal VLM) | [Qwen/Qwen2.5-VL-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct) | Qwen Research / Apache-2.0 | High-accuracy reference multimodal baseline for complex invoice table and line-item extraction. |
| **CORD-v2 Dataset** | Dataset | [naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) | CC-BY-4.0 | Consolidated Receipt Dataset for post-OCR parsing and hierarchical receipt item extraction. |
| **Invoices Donut Dataset v1** | Dataset | [katanaml-org/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) | MIT | Annotated synthetic and real invoice images paired with JSON ground truth for end-to-end document VLM evaluation. |
| **Qwen2-VL Receipt LoRA Card** | Model Card | [chai1me/qwen2vl-receipt-lora](https://huggingface.co/chai1me/qwen2vl-receipt-lora) | Apache-2.0 | Architectural reference configuration for receipt line-item extraction LoRA hyperparameters. |
| **Qwen2-VL CORD LoRA Card** | Model Card | [saliousk/qwen2vl-cord-lora](https://huggingface.co/saliousk/qwen2vl-cord-lora) | Apache-2.0 | Architectural reference configuration for CORD-v2 parsing with vision-language adapters. |

---

## Track C: Prohibited Item Screening & Deterministic Policy

| Asset Name | Type | Source URL / Repository | License | Purpose in System |
| :--- | :--- | :--- | :--- | :--- |
| **Qwen3-1.7B** | Model (LLM) | [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) | Apache-2.0 | Fast, compact language model for zero-shot and LoRA-based line-item classification into security categories. |
| **Item Taxonomy Seed Dataset** | Dataset | `research_track/datasets/item_taxonomy_seed/seed_items.csv` | Project Internal (Synthetic) | 300 unique synthetic line items (quick-commerce truncations, Hinglish slang, normal groceries) mapped across 7 institutional security categories. |
| **Screening Policy Schema** | SQL / Models | `research_track/db_draft/` | Project Internal | Staging DDL, Alembic migration draft, and SQLAlchemy 2.0 models decoupling probabilistic classification from deterministic security policy. |
