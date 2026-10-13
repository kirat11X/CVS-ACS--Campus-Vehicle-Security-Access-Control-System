# Research Literature and Findings: PEC Campus Vehicle Security ML Track

Date: 2026-10-09. Companion to `irl_significance.md` (why it matters in practice) and `finetune/RESULTS_A.md`, `finetune/RESULTS_C.md` (measured numbers).

**Local library:** 22 papers (89 MB), downloaded from arXiv to `~/ml-assets/campus/papers/` (outside the repository). `papers_manifest.json` there records title, authors, date, abstract, size and SHA-256 for every PDF. These copies are for private study; cite the arXiv URLs and do not commit or redistribute the PDFs. Every claim about a paper below was checked against its abstract or full text. Where a number is quoted, the section it came from is noted.

---

## 1. Research questions

| ID | Question | Track |
|---|---|---|
| RQ-A1 | How well do pretrained plate readers built for other countries read Indian plates (HSRP, older plates, two-line, BH series)? How much does Indian-specific fine-tuning add? | A |
| RQ-A2 | Can registry-constrained fuzzy matching with an explicit ambiguity margin turn noisy OCR into safe suggestions (EXACT / FUZZY_CONFIDENT / AMBIGUOUS / NO_MATCH)? | A |
| RQ-B1 | Can a small vision-language model extract invoice line items reliably enough that arithmetic checks catch the remaining errors? (Not approved for training.) | B |
| RQ-C1 | Does a 4-bit QLoRA-adapted 1.7B LLM beat lexical, embedding-kNN and zero-shot baselines at proposing item categories, including Hinglish and truncated quick-commerce SKUs? | C |
| RQ-X1 | How should ML perception be separated from deterministic policy and human decisions so that errors stay safe and auditable? | All |

## 2. Literature by track

### Track A: Indian plate detection and recognition

| Paper | What it establishes (verified) | How this project uses it |
|---|---|---|
| **Indian Licence Plate Dataset in the wild**. Tanwar et al., 2021, [arXiv:2111.06054](https://arxiv.org/abs/2111.06054) | 16,192 images, 21,683 plates from 10 states, 4-point plate polygons plus character labels. Stage 1: object detection AP50 0.8310 (12 FPS) vs semantic segmentation 0.8313 (14 FPS). Stage 2: LPRNet **character accuracy 75.6% on 4-point-warped crops vs 66.3% on rectangular crops** (Table 3). Only fully readable plates were annotated; unreadable or partially readable plates were not (Sec. 3). Dataset withheld for legal reasons (repo README). | Source of the pretrained `best_lprnet.pth` used zero-shot. Motivates rectifying crops with 4 points before OCR (`a_build_crops.py` design). Its "readable plates only" annotation explains why the model never learned to abstain. |
| **Exploration of an E2E ANPR network for Indian datasets**. Nadiminti et al., 2022, [arXiv:2207.06657](https://arxiv.org/abs/2207.06657) | Releases a 1.5k-image Indian set. A CCPD-designed E2E model transfers poorly to Indian plates because of their extreme diversity; aligning data characteristics improved detection by 42.86%. A COCO-pretrained YOLOv5 fine-tuned on the same Indian images was **more sample-efficient than starting from CCPD**. | Supports starting the plate detector from a COCO-pretrained YOLO (YOLO11n) rather than a Chinese-plate model. |
| **LPRNet**. Zherzdev & Gruzdev, 2018, [arXiv:1806.10447](https://arxiv.org/abs/1806.10447) | Segmentation-free, RNN-free CNN with CTC decoding; up to 95% on Chinese plates; 3 ms/plate on a GTX 1080, 1.3 ms on an i7-6700K CPU. | The architecture behind the Indian LPRNet weights. Its CPU speed supports on-premise deployment. |
| **Robust Real-Time ALPR based on YOLO**. Laroca et al., 2018, [arXiv:1802.09567](https://arxiv.org/abs/1802.09567) | YOLO-based multi-stage ALPR; 93.53% recognition at 47 FPS on SSIG, beating two commercial systems. Introduces UFPR-ALPR (academic licence required). | Reference two-stage design (detect → recognise). UFPR-ALPR is listed as MANUAL in the dataset manifest. |
| **Do We Train on Test Data? Near-duplicates in LPR**. Laroca et al., 2023, [arXiv:2304.04653](https://arxiv.org/abs/2304.04653) | Near-duplicates (different images of the same plate) in train and test: **46.9% (AOLP-A), 67.6% (AOLP-B), 19.1% (CCPD) and 68.6% (ReId) of test images**. Under duplicate-free splits, CCPD average recognition fell from 80.3% to 77.6%, and model rankings changed on AOLP. | **Core methodological basis.** Track A splits must group by plate string (no same-plate leakage). Also explains why the pretrained LPRNet's 21/23 on IN-02 may be optimistic: its authors recommend that same Kaggle set. |
| **Compact Convolutional Transformers (CCT)**. Hassani et al., 2021, [arXiv:2104.05704](https://arxiv.org/abs/2104.05704) | Convolutional tokenisation lets small transformers (as few as 0.28M parameters) avoid overfitting and beat CNNs on small datasets. | fast-plate-ocr's only trainable architecture (`model: cct` in its schema) and the `cct-s-v2-global` model (MIT) used zero-shot. The intended fine-tuning initialisation for Indian plates. |
| **MobileViT-v2 (separable self-attention)**. Mehta & Rastegari, 2022, [arXiv:2206.02680](https://arxiv.org/abs/2206.02680) | Replaces O(k²) multi-head attention with linear-complexity separable self-attention for mobile latency. | Architecture of the legacy European fast-plate-ocr model. It is inference-only (no trainable config), so it serves as the baseline only. |
| **YOLOv9 (PGI / GELAN)**. Wang et al., 2024, [arXiv:2402.13616](https://arxiv.org/abs/2402.13616) | Programmable gradient information addresses information loss through deep layers. | The staged `open-image-models` plate detectors are YOLOv9 ONNX models. Note that the project's own detectors use Ultralytics YOLO11n, which has no official paper; cite the Ultralytics software instead. |
| **PaddleOCR-VL**. Cui et al., 2025, [arXiv:2510.14528](https://arxiv.org/abs/2510.14528) | 0.9B VLM (NaViT-style encoder + ERNIE-4.5-0.3B), 109 languages; state of the art on document parsing. | Staged as a possible "second reader" for hard plates. **Untested on plates**: it is a document model, so plate performance is an open question. |

### Track B: Invoice extraction (staged, not approved for training)

| Paper | What it establishes | Relevance |
|---|---|---|
| **Donut, OCR-free Document Understanding Transformer**. Kim et al., 2021, [arXiv:2111.15664](https://arxiv.org/abs/2111.15664) | OCR pipelines suffer from cost, inflexibility and OCR error propagation; an end-to-end model avoids a separate OCR step. | Background for the OCR-free VLM approach. The staged `invoices-donut-data-v1` set comes from this line of work. |
| **Qwen2.5-VL Technical Report**. Bai et al., 2025, [arXiv:2502.13923](https://arxiv.org/abs/2502.13923) | Strong localisation and document parsing; explicit structured extraction from invoices, forms and tables. | Reference baseline (3B) in `LINKS.md`. |
| **Qwen3-VL Technical Report**. Bai et al., 2025, [arXiv:2511.21631](https://arxiv.org/abs/2511.21631) | Dense 2B/4B/8B/32B and MoE variants; 256K interleaved context; text ability preserved. | Qwen3-VL-2B-Instruct is staged as the small on-premise extractor candidate. |

Not on arXiv: **CORD**, Park et al., "CORD: A Consolidated Receipt Dataset for Post-OCR Parsing", NeurIPS 2019 Document Intelligence Workshop (staged dataset, CC-BY-4.0).

### Track C: Item-category proposal

| Paper | What it establishes | How this project uses it |
|---|---|---|
| **LoRA**. Hu et al., 2021, [arXiv:2106.09685](https://arxiv.org/abs/2106.09685) | Freezes the pretrained weights and trains low-rank update matrices, cutting trainable parameters greatly. | Adapter design: r=16, alpha=32 on q/k/v/o/gate/up/down. |
| **QLoRA**. Dettmers et al., 2023, [arXiv:2305.14314](https://arxiv.org/abs/2305.14314) | Back-propagates through a frozen 4-bit (NF4) model into LoRA adapters while preserving 16-bit fine-tuning performance (at the authors' scales); double quantisation and paged optimisers. | Exactly the recipe used: NF4 + double quantisation, bf16 compute. It is why a 1.7B model trained in 3.77 GiB of VRAM on a laptop GPU. |
| **Qwen3 Technical Report**. Yang et al., 2025, [arXiv:2505.09388](https://arxiv.org/abs/2505.09388) | Dense and MoE models from 0.6B to 235B with unified thinking / non-thinking modes. | Base model Qwen3-1.7B (Apache-2.0); thinking mode disabled for short classification outputs. |
| **Sentence-BERT**. Reimers & Gurevych, 2019, [arXiv:1908.10084](https://arxiv.org/abs/1908.10084) | Siamese BERT produces sentence embeddings for fast similarity search (vs about 65 h of BERT cross-encoding for 10k sentences). | MiniLM kNN baseline for Track C; embedding-based registry matching idea for Track A. |
| **MiniLM**. Wang et al., 2020, [arXiv:2002.10957](https://arxiv.org/abs/2002.10957) | Deep self-attention distillation compresses transformers for low-latency serving. | Backbone of `paraphrase-multilingual-MiniLM-L12-v2`. |
| **Multilingual knowledge distillation**. Reimers & Gurevych, 2020, [arXiv:2004.09813](https://arxiv.org/abs/2004.09813) | Extends monolingual sentence embeddings to new languages by training on translations to mimic the teacher. | Why the multilingual MiniLM is a reasonable baseline for Hinglish item text. |

### Cross-cutting: evaluation, documentation, human–AI decisions

| Paper | What it establishes | How this project uses it |
|---|---|---|
| **On Calibration of Modern Neural Networks**. Guo et al., 2017, [arXiv:1706.04599](https://arxiv.org/abs/1706.04599) | Modern deep networks are poorly calibrated; **temperature scaling** (one parameter) is a surprisingly effective fix. | Track C emits `confidence=None` today, which forces REVIEW. Next step: temperature-scale label-token probabilities on the validation split before any model NORMAL may contribute to ALLOW. |
| **Datasheets for Datasets**. Gebru et al., 2018, [arXiv:1803.09010](https://arxiv.org/abs/1803.09010) | Every dataset should document its motivation, composition, collection, uses and limits. | `MANIFEST.yaml` / `MANIFEST_ADDENDUM.yaml` and provenance labels. A full datasheet is still needed for any PEC data. |
| **Model Cards for Model Reporting**. Mitchell et al., 2018, [arXiv:1810.03993](https://arxiv.org/abs/1810.03993) | Trained models should ship with intended use, evaluation conditions and limitations. | `finetune/MODEL_CARD_C_full_c_v1.md`; required for every artifact. |
| **Does the Whole Exceed its Parts? AI explanations and team performance**. Bansal et al., 2020, [arXiv:2006.14779](https://arxiv.org/abs/2006.14779) | AI help gave complementary gains, but **explanations increased acceptance of the AI's recommendation regardless of its correctness**. | Direct risk for the guard interface. Showing reasons must not become rubber-stamping, so measure guard override rates and design for appropriate reliance. |

Not on arXiv (cited, not downloaded): Xu et al., "Towards End-to-End License Plate Detection and Recognition: A Large Dataset and Baseline" (CCPD), ECCV 2018. Hsu et al., "Application-Oriented License Plate Recognition" (AOLP), IEEE T-VT 2013. Efron & Tibshirani, *An Introduction to the Bootstrap*, 1993 (percentile bootstrap CIs). Clopper & Pearson, Biometrika 1934 (exact binomial CIs). Software: fast-plate-ocr (MIT, github.com/ankandrew/fast-plate-ocr), Ultralytics YOLO11 (AGPL-3.0).

## 3. Methodology choices grounded in the literature

1. **Leakage-free splits.** Laroca et al. (2023) show that near-duplicates inflate LPR results and can reorder models. So Track A splits group by plate string, and Track C splits group by brand/template family (191 families, union-find over shared tokens, consonant skeletons and near-duplicate similarity).
2. **Test split used once.** The selection is made on validation; the test split is locked after a single evaluation (`runs/C/eval/TEST_EVALUATED.lock`).
3. **Uncertainty on every number.** Percentile bootstrap (2,000 resamples, paired across models) for Track C. Exact Clopper–Pearson intervals for small counts (Track A informal check).
4. **Rectify before reading.** Indian LPR's 75.6% vs 66.3% (warped vs rectangular crops) motivates 4-point rectification in the Track A crop builder.
5. **Detector initialisation.** Nadiminti et al. found COCO-pretrained YOLO more sample-efficient than a CCPD start for Indian plates, so the detectors start from COCO-pretrained YOLO11n.
6. **Calibration before automation.** Following Guo et al., a model's label is not treated as reliable confidence until it is calibrated. Until then missing confidence means REVIEW.
7. **Documentation.** Datasheets / model cards (Gebru; Mitchell) become MANIFEST entries, model cards and mandatory provenance labels.
8. **Human–AI teaming.** Bansal et al.'s finding drives the "observation ≠ decision" invariant and the plan to monitor guard override rates.

## 4. Findings so far, compared with the literature

All numbers carry their provenance labels; none is PEC gate performance.

| Finding | Number | Literature comparison |
|---|---|---|
| Pretrained **Indian LPRNet** on 1,840 IN-02 crops (zero-shot, no training) | Indian-format-valid 92.2%; informal visual check **21/23**, exact 95% CI [0.72, 0.99]. *"IN-02 Kaggle CC0 crops, no text ground truth; NOT PEC gate performance"* | Its own paper reports **75.6% character accuracy** on its Indian test set. The much higher result here suggests easier, clean, frontal crops and/or overlap with LPRNet's training data, which is exactly the near-duplicate effect of Laroca et al. Treat it as optimistic. |
| Global **CCT-S v2** (MIT) zero-shot | Format-valid 69.5%; 12/23 [0.31, 0.73] | India is not among its training regions. This confirms both Indian ANPR papers' claim that foreign-trained readers transfer poorly. |
| European **MobileViT-v2** zero-shot | 0/23 [0.00, 0.15] | 9 output slots cannot represent 10-character Indian plates: a structural failure, not just a domain gap. |
| LPRNet **hallucination** on an illegible crop (`MH09BB4445`) | 1 of 1 illegible crop | Explained by the Indian LPR annotation policy (readable plates only), so the model never saw "unreadable". Supports the human-in-the-loop invariant and an explicit reject option. |
| **Plate detector** (YOLO11n, 145/36 Kaggle images) | mAP50 0.897, mAP50-95 0.686 (validation) | Consistent with the COCO-pretrained transfer finding of Nadiminti et al. Small validation set (36 images), so wide uncertainty. |
| **Track C QLoRA** Qwen3-1.7B (n=63 test) | Accuracy **0.841 [0.746, 0.921]**, macro-F1 0.818 vs lexical 0.365, zero-shot 0.333. *"synthetic LLM-authored items; measures fit to that distribution, not real invoice accuracy"* | Consistent with QLoRA's claim that 4-bit adapters fine-tune effectively. Zero-shot Qwen3 produced 14.3% invalid outputs, so adaptation is needed for a fixed label set. |
| Track C safety error | 1 gold-UNKNOWN item → NORMAL (QLoRA); 3 for MiniLM kNN | Calibration (Guo et al.) and the UNKNOWN ≠ NORMAL rule are both needed. |

## 5. Research gaps this project addresses

1. **No public, license-clear Indian plate-text dataset.** The largest (Indian LPR, 16k images) is withheld. The other options found are detection-only, out of domain (the Roboflow "carpallet" set is Iranian), or behind a login. A consented, hand-labelled PEC evaluation set would itself be a contribution.
2. **Evaluation hygiene in Indian ANPR.** Neither Indian ANPR paper reviewed here describes how its splits keep the same plate or source video out of both train and test, and neither reports confidence intervals. Indian LPR's images were "filtered out from videos" (Sec. 3) and evaluated on a 3,400-image test split (Sec. 5), which is the setting where Laroca et al. found heavy near-duplicate contamination. Applying a duplicate-free protocol to Indian data is a gap.
3. **Abstention for plate OCR.** Readers trained only on readable plates cannot say "unreadable". A reject or abstain signal for gate use is under-studied.
4. **Category proposal for Indian quick-commerce text** (Hinglish, truncated SKUs) separated from policy has no direct prior work that we found.
5. **Perception–policy separation with audit** as an explicit architecture for campus security, evaluated with human override metrics.

## 6. Open research questions and next experiments

1. Hand-label about 200 IN-02 crops, then measure plate accuracy and CER with CIs for LPRNet vs CCT-global (RQ-A1).
2. Fine-tune `cct-s-v2-global` (MIT) on licensed Indian text labels with plate-grouped splits; compare against zero-shot (RQ-A1).
3. Add an abstain option: per-character confidence threshold (CCT exposes `char_probs`) and an "unreadable" class.
4. Evaluate registry matching thresholds (0.82 / Δ 0.07) on PEC-like confusions such as 0/O, 8/B and 1/I (RQ-A2).
5. Temperature-scale Track C label probabilities on validation; report the expected calibration error (RQ-C1).
6. Real, consented invoice line items with human labels, including UNKNOWN and ambiguous items (RQ-C1, RQ-B1).
7. Shadow-mode pilot at one gate: guard override rate, false alerts per 100 vehicles, time to clear (RQ-X1; Bansal et al.).

## 7. Paper index (local copies)

Directory: `~/ml-assets/campus/papers/`. Full metadata and full SHA-256 values are in `papers_manifest.json`.

| arXiv | Year | First author | Title | File | Size | SHA-256 (prefix) |
|---|---|---|---|---|---|---|
| [2111.06054](https://arxiv.org/abs/2111.06054) | 2021 | Tanwar | Indian Licence Plate Dataset in the wild | `2111.06054.pdf` | 5.1 MB | `858805c7357f` |
| [2207.06657](https://arxiv.org/abs/2207.06657) | 2022 | Nadiminti | Exploration of an End-to-End Automatic Number-plate Recognition neural network for Indian datasets | `2207.06657.pdf` | 0.7 MB | `4dc2b91e80a5` |
| [1806.10447](https://arxiv.org/abs/1806.10447) | 2018 | Zherzdev | LPRNet: License Plate Recognition via Deep Neural Networks | `1806.10447.pdf` | 0.3 MB | `c34985175f7b` |
| [1802.09567](https://arxiv.org/abs/1802.09567) | 2018 | Laroca | A Robust Real-Time Automatic License Plate Recognition Based on the YOLO Detector | `1802.09567.pdf` | 5.9 MB | `3f44d7ad641f` |
| [2304.04653](https://arxiv.org/abs/2304.04653) | 2023 | Laroca | Do We Train on Test Data? The Impact of Near-Duplicates on License Plate Recognition | `2304.04653.pdf` | 2.4 MB | `69358dff47d3` |
| [2104.05704](https://arxiv.org/abs/2104.05704) | 2021 | Hassani | Escaping the Big Data Paradigm with Compact Transformers | `2104.05704.pdf` | 0.5 MB | `741c10e43c97` |
| [2206.02680](https://arxiv.org/abs/2206.02680) | 2022 | Mehta | Separable Self-attention for Mobile Vision Transformers | `2206.02680.pdf` | 7.7 MB | `ca134b596dda` |
| [2402.13616](https://arxiv.org/abs/2402.13616) | 2024 | Wang | YOLOv9: Learning What You Want to Learn Using Programmable Gradient Information | `2402.13616.pdf` | 5.0 MB | `5a67aef4802d` |
| [2510.14528](https://arxiv.org/abs/2510.14528) | 2025 | Cui | PaddleOCR-VL: Boosting Multilingual Document Parsing via a 0.9B Ultra-Compact Vision-Language Model | `2510.14528.pdf` | 36.3 MB | `fc9038ee91c5` |
| [2111.15664](https://arxiv.org/abs/2111.15664) | 2021 | Kim | OCR-free Document Understanding Transformer | `2111.15664.pdf` | 7.1 MB | `ad9c20523c37` |
| [2502.13923](https://arxiv.org/abs/2502.13923) | 2025 | Bai | Qwen2.5-VL Technical Report | `2502.13923.pdf` | 2.2 MB | `399a28f6ed79` |
| [2511.21631](https://arxiv.org/abs/2511.21631) | 2025 | Bai | Qwen3-VL Technical Report | `2511.21631.pdf` | 4.4 MB | `ee075d08e67d` |
| [2106.09685](https://arxiv.org/abs/2106.09685) | 2021 | Hu | LoRA: Low-Rank Adaptation of Large Language Models | `2106.09685.pdf` | 1.6 MB | `e9a0d3128767` |
| [2305.14314](https://arxiv.org/abs/2305.14314) | 2023 | Dettmers | QLoRA: Efficient Finetuning of Quantized LLMs | `2305.14314.pdf` | 1.1 MB | `33a4e757c19d` |
| [2505.09388](https://arxiv.org/abs/2505.09388) | 2025 | Yang | Qwen3 Technical Report | `2505.09388.pdf` | 0.8 MB | `84a5e2b1fa04` |
| [1908.10084](https://arxiv.org/abs/1908.10084) | 2019 | Reimers | Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks | `1908.10084.pdf` | 0.5 MB | `92366d22fc05` |
| [2002.10957](https://arxiv.org/abs/2002.10957) | 2020 | Wang | MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers | `2002.10957.pdf` | 0.6 MB | `f2c36bbb2be0` |
| [2004.09813](https://arxiv.org/abs/2004.09813) | 2020 | Reimers | Making Monolingual Sentence Embeddings Multilingual using Knowledge Distillation | `2004.09813.pdf` | 0.7 MB | `9f23b079d0c6` |
| [1706.04599](https://arxiv.org/abs/1706.04599) | 2017 | Guo | On Calibration of Modern Neural Networks | `1706.04599.pdf` | 1.3 MB | `cb654a65acb7` |
| [1803.09010](https://arxiv.org/abs/1803.09010) | 2018 | Gebru | Datasheets for Datasets | `1803.09010.pdf` | 0.6 MB | `c7f595988ee2` |
| [1810.03993](https://arxiv.org/abs/1810.03993) | 2018 | Mitchell | Model Cards for Model Reporting | `1810.03993.pdf` | 1.0 MB | `a4049cdc78c3` |
| [2006.14779](https://arxiv.org/abs/2006.14779) | 2020 | Bansal | Does the Whole Exceed its Parts? The Effect of AI Explanations on Complementary Team Performance | `2006.14779.pdf` | 3.4 MB | `9a00f4566bf0` |

Total: 22 papers, 89.3 MB.
