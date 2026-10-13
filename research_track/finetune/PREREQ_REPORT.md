# Prerequisite Report (Phase 1): G3 `APPROVE_FINETUNE:A,C:local:0`

Date: 2026-10-09. Host: Fedora 44, i7-13650HX (20 threads), RTX 4050 Laptop 6 GB.
Phase 1 was read-only except for GPU/CUDA probes (a bitsandbytes 4-bit linear forward and Keras backend device probes, peak <1 MiB allocated).
Claims in REVIEW_REPORT.md, OPEN_DECISIONS.md, PROGRESS.md and FINETUNE_DECISION.md were treated as unverified and re-checked below.

## 1. Resources

| Check | Threshold | Result | Evidence |
|---|---|---|---|
| GPU VRAM in use | < 1 GB | PASS | `nvidia-smi`: `12MiB / 6141MiB`, P8, 41 C, 5 W; only process `gnome-shell` (1 MiB); driver/KMD 615.71.09, CUDA UMD 13.4 |
| MemAvailable | >= 8 GB | PASS | `/proc/meminfo`: `MemAvailable: 10587380 kB` (10.1 GiB) of 15.3 GiB; swap 8.0 GiB total, 5.0 GiB free |
| Disk free | >= 45 GB before downloads | PASS | `df -h /home`: `449G size, 360G used, 86G avail, 81%` |
| Load | informational | PASS | `/proc/loadavg`: `0.49 0.64 0.93` (20 CPUs) |
| Top memory consumers | informational | INFO | VS Code `code` processes (largest 0.58 GiB RSS), `claude` 0.31 GiB, `codex` 0.18 GiB. No Docker/Postgres/broker process appears in the top 15. The earlier ~3 GB RAM figure no longer applies. |
| AC power | on AC | PASS (re-check) | 05:16:30 first probe: `AC online=0`, `BAT0 Discharging 67%` -> **FAIL**. 05:18:36 re-check: `AC/online=1`, `BAT0 Charging 67%` -> PASS. The launchers re-check AC before each run. |

## 2. Software (`~/ml-assets/campus/.venv-ml`)

| Check | Result | Evidence |
|---|---|---|
| Python 3.12 | PASS | `Python 3.12.11` |
| torch CUDA build | PASS | `torch 2.14.1+cu130 cuda_build 13.0 cudnn 92400`, `cuda_available True`, `RTX 4050 Laptop cap (8, 9) bf16 True` |
| bitsandbytes 4-bit forward on GPU | PASS | `bitsandbytes 0.50.2`: `Linear4bit(64->32, nf4, bf16)` forward -> `bnb4bit_forward_ok (4, 32) torch.bfloat16 finite True` |
| transformers/peft/trl/accelerate + Qwen3 | PASS | `transformers 5.17.0, peft 0.21.2, trl 1.13.0, accelerate 1.15.0`; `AutoConfig` -> `qwen3 ['Qwen3ForCausalLM'] layers 28 hidden 2048`; `Qwen3ForCausalLM_present True`; `LoraConfig`/`SFTTrainer`/`SFTConfig` import OK |
| keras + backend needed by fast-plate-ocr | WARN, worked around | `keras 3.15.1`. From source: `fast_plate_ocr/train/utilities/backend_utils.py` accepts `jax`/`tensorflow`/`torch`; train code uses backend-agnostic `keras.*` (TF is imported only in `cli/export.py` for TFLite/CoreML). `~/.keras/keras.json` defaults to `tensorflow`, but `tf 2.21.0 built_with_cuda True gpus []` (`Failed call to cudaGetRuntimeVersion: Error loading CUDA libraries`): TF has **no GPU**. `KERAS_BACKEND=torch` gives `torch cuda True`, and the op runs on `cuda:0`. **Decision: train with `KERAS_BACKEND=torch`.** No package change is needed and `keras.json` is not edited. |
| onnxruntime providers | PASS (CPU) | `onnxruntime 1.30.0`: `['AzureExecutionProvider', 'CPUExecutionProvider']`. CPU is enough for parity checks. |
| Other | PASS | `fast-plate-ocr 1.1.0` (installed), `tf2onnx 1.17.0`, `onnx 1.23.2`, `albumentations 2.0.8`, `sentence-transformers 6.1.0`, `scikit-learn 1.9.1`, `gdown 6.4.1`, `kaggle 2.2.4`, `huggingface-hub 1.33.0`, `opencv-python-headless 5.0.0.93` |

No version conflicts were found and no package changes were made.

## 3. Assets (MANIFEST.yaml vs filesystem)

| Asset | Result | Evidence |
|---|---|---|
| `code/fast-plate-ocr` + train CLI | PASS | git `9ce7a5b6` (2026-03-14), v1.1.0, entry point `fast-plate-ocr = fast_plate_ocr.cli.cli:main_cli`, `cli/train.py` present. License in `pyproject.toml` is **MIT** (MANIFEST says Apache-2.0; corrected in the addendum). |
| european-plates-mobile-vit-v2 ONNX | PASS hash, **WARN usability** | sha256 `5f388f57…6943f`, 4,985,005 B (matches MANIFEST). Config sha256 `202b90f2…aaf`: `max_plate_slots: 9`, alphabet `0-9A-Z_`, 70x140. The model zoo lists it under *Legacy Models*: "for compatibility and inference only… not recommended for fine-tuning". The repo has no Keras architecture YAML for MobileViT (the trainable schema supports only `model: cct`) and no `.keras` checkpoint, so `--weights-path` cannot use it. **Usable only as the zero-shot baseline.** |
| Qwen3-1.7B | PASS | 2 shards, header-derived sizes match on-disk sizes (`3441185608 OK`, `622329984 OK`), 311 tensors, matching the index. sha256 (<1 GB files): config.json `1ddb5b89…`, tokenizer.json `aeb13307…`, vocab.json `ca10d7e9…`, merges.txt `8831e4f1…`, generation_config `2325da0f…`, tokenizer_config `d5d09f07…`, index `0d660e94…`. LICENSE: Apache-2.0. |
| MiniLM (paraphrase-multilingual-L12-v2) | PASS | `model.safetensors` sha256 `eaa086f0…917b`, 470,641,600 B (matches MANIFEST); `1_Pooling`, tokenizer and ST configs are present. |

## 4. Dataset completeness

### Track A

| Item | Needed | Present | Gap |
|---|---|---|---|
| Indian LPR "in the wild" (arXiv 2111.06054) | 16,192 images, 21,683 plates, 4-point + per-character annotations | **0 images, 0 annotations.** The clone holds code, 3 `.pth` weights and 4 demo images (`demo_images/`). | **100%.** The README says verbatim: "We can't make dataset public because of legalities involved in making Indian Road data public". No download link exists. The repo has **no LICENSE file** (all rights reserved by default). |
| Any other authorized Indian plate crops with text labels | ≥ a few thousand crops | 0 | Full gap. Kaggle `kedarsai/indian-license-plates-with-labels` needs `~/.kaggle/kaggle.json`, which is absent (`No such file or directory`). IEEE DataPort needs a login. |

PIL verification, annotation parsing and the paper count comparison cannot run because there are no files.

### Track C

| Item | Needed | Present | Gap / note |
|---|---|---|---|
| `datasets/item_taxonomy_seed/seed_items.csv` | 300 rows (MANIFEST) | 300 rows, sha256 `150a1bef…5e5a` (matches) | Columns `item_text, category, style`. |
| Class balance | 8 codes | NORMAL 140, TOBACCO_NICOTINE 30, ALCOHOL 30, OTC_MEDICINE 30, RX_SCHEDULED_DRUG 25, HAZARDOUS_CHEMICAL 25, SHARP_OBJECT 20, **UNKNOWN 0** | The seed has no UNKNOWN rows. `track_c/fixtures/item_taxonomy_seed.csv` has 320 rows = the same 300 + **20 UNKNOWN**. This explains review finding C-S2-004 (320 vs 300). |
| Duplicates | none | exact 0, case-folded 0, punctuation-normalized 0 | — |
| Near-duplicates | flag | 1 pair, SequenceMatcher ≥ 0.9: `Amul Butter 500g` / `Amul Buttr 500` (0.93) | It must stay in one split group (handled by the family grouping). |
| Brand/template family | needed for the grouped split | no column | Must be derived (first brand token + category). |

## 5. Code readiness (fast-plate-ocr, read from source)

- **Train CLI** (`cli/train.py`): required `--model-config-file`, `--plate-config-file`, `--annotations`, `--val-annotations`. Optional: `--weights-path` (Keras weights, loaded with `skip_mismatch=True`), `--epochs 150`, `--batch-size 64`, `--lr 1e-3`, cosine decay with `--warmup-fraction 0.05`, `--mixed-precision-policy {mixed_float16,mixed_bfloat16,float32}`, `--early-stopping-metric` (`val_plate_acc` by default; there is **no CER metric**, the closest is `val_plate_char_acc`), `--early-stopping-patience 100`, `--seed`, `--use-ema` (on by default), `--validate-dataset off|warn|error`, `--output-dir` (a timestamped subdir is appended). It writes `best.keras`, `last.keras` (every epoch), `training_log.csv` and `hyper_params.json`. It has **no resume flag**; resuming is possible by passing `last.keras` as `--weights-path`, but the optimizer and LR-schedule state restart.
- **Plate config schema** (`train/model/config.py`, pydantic `extra=forbid`): `max_plate_slots`, `alphabet`, `pad_char` (must be in the alphabet), `img_height`, `img_width`, `keep_aspect_ratio=False`, `interpolation=linear`, `image_color_mode=grayscale|rgb`, `padding_color`, `plate_regions` (optional; enables the region head).
- **CSV format**: columns `image_path` (relative to the CSV), `plate_text` (no padding), and optional `plate_region`.
- **Head compatibility for Indian plates**: Indian plates use `0-9A-Z` and are at most 10 characters (`MH12AB1234`, BH-series `22BH1234AA`). Older 11-character Delhi formats such as `DL10CAB1234` exist, so **11 slots** is the safe choice. The european head has 9 slots, so `MH12AB1234` (10) cannot be emitted at all. Two-line plates are a crop and rectification issue, not an alphabet issue: the model reads the whole crop, so rows are concatenated top-to-bottom in the label.
- **Decision**: the european MobileViT-v2 is **baseline-only**, because no trainable architecture or Keras weights exist. Training initializes from the modern `cct_s_v2_global.keras` (model zoo default, ~MB-scale download, same MIT repo) with an 11-slot plate config. The per-slot head is shape-mismatched and **re-initialized** via `skip_mismatch=True`; the backbone is reused. The fallback is training from scratch.
- Review coverage (46%) and unfinished mutation testing were noted. Per instructions, they do not block training.

## Gate 1

- Resource thresholds: **all PASS** on re-check. AC was briefly on battery at 05:16 and is now on AC.
- Software: PASS (Keras must run with `KERAS_BACKEND=torch`).
- **Track A: the real-data gap is total (0 / 16,192).** It moves to Phase 2. If no license-clear, login-free Indian plate set with text labels can be obtained, Track A stops at Phase 2.5 per the instructions.
- Track C: data is present (synthetic, 300 + 20 UNKNOWN).

## Phase 2 re-check (data completion)

Re-run of the section 4 dataset checks after Phase 2 (2026-10-09 05:2x):

| Track | Needed | Present after Phase 2 | Status |
|---|---|---|---|
| A, real Indian plates with human text labels | thousands of crops | **0** | **GAP REMAINS -> STOP (Phase 2.5).** Indian_LPR: withheld by the authors (MANUAL). Kaggle: no `kaggle.json` (MANUAL). IEEE DataPort: login-gated (MANUAL). HF Hub search: 10 candidates, all rejected (empty placeholder repos, machine-generated labels, no license, or NC-ND vendor sample); see `MANIFEST_ADDENDUM.yaml`. |
| C, synthetic taxonomy | 8 codes | 300 seed + 20 UNKNOWN (fixture) | Unchanged; ready. |

New downloads: **0 GB of 30 GB**. Network use was HF Hub API metadata and README reads only.

## Re-audit 2026-10-09 09:03 (same G3 token; read-only + GPU probe)

| Check | Result | Evidence |
|---|---|---|
| GPU VRAM in use | PASS | `nvidia-smi`: 12MiB / 6141MiB, 40 C, P8; only gnome-shell |
| MemAvailable >= 8 GB | **WARN/FAIL (borderline)** | `MemAvailable: 7935608 kB` = 7.57 GiB (8.13 GB decimal). Project services are running: `uvicorn backend.app.main:app --port 8000` (PID 27056) and `python3 -m frigate` (PID 4489); swap 3 GiB used. Before any further GPU training the user must stop these themselves. |
| Disk free | PASS | `df -h /home`: 84G avail (82%) |
| AC power | PASS | `AC online=1`, `BAT0 Not charging` |
| Software | PASS | python 3.12.11; torch 2.14.1+cu130 `cuda True` RTX 4050; bnb 0.50.2 Linear4bit forward `(4,32) finite True`; transformers 5.17.0 / peft 0.21.2 / trl 1.13.0 / accelerate 1.15.0; keras 3.15.1; ultralytics 8.4.174; onnxruntime 1.30.0 [Azure, CPU]; `fast-plate-ocr train` CLI present. TF 2.21 still "Could not find cuda drivers" -> keep `KERAS_BACKEND=torch`. |
| Image integrity | PASS | PIL `verify()` on 21,437 images (IN-02 2,083 + carpallet 19,354): 0 bad |

### Dataset inventory (installed under ~/ml-assets/campus/datasets)

| Dataset | Size | Content (verified) | Usable for Track A OCR? |
|---|---|---|---|
| IN-02 Kaggle kedarsai (CC0-1.0) | 166M | 2,083 images (181 full-scene JPG + 1,902 pre-cropped plate PNG), 2,021 YOLO label files, single class `0`; PNG labels are one box covering the whole crop (e.g. `0 0.477 0.507 0.955 0.901`); 62 PNGs have no label | **No**: no plate text. The 1,840 labelled PNG crops are real Indian plates and would be OCR-ready if text labels were added by hand. |
| ROBOFLOW carpallet license-plate-takqm v1 (CC BY 4.0) | 816M | 19,354 images (13,544/3,873/1,937), 12 classes `- , - - - -, 0-9`; visual inspection of 8 random images: **Iranian plates, Persian digits** | **No**: wrong script/country. Out of domain for Indian plates. |
| ROBOFLOW vehicle-detection-2g9na v1 (CC BY 4.0) | 97M | 2,256 images, classes taxi/truck | No (vehicle detection only) |
| GL-03 CCPD source | 62M | repo metadata only, no images | No |
| cord-v2, invoices-donut-data-v1 | 2.4G | Track B assets | Not approved (Track B) |
| Indian_LPR (arXiv 2111.06054) | 0 | code + 4 demo images; data withheld by authors | MANUAL |

### Failures / anomalies found

1. **Track A OCR still has 0 real text-labelled Indian plates.** No installed dataset carries plate strings. Blocking for OCR fine-tune.
2. `runs/track_a/20261009_character_detector` (YOLO11n, 20 ep, final val P .976 R .897 mAP50 .906 mAP50-95 .690) was trained on the **Iranian** carpallet set; it is not recorded in RESULTS_A.md/PROGRESS and must not be cited as Indian plate performance.
3. `runs/track_a/20261009_vehicle_detector` (taxi/truck, final mAP50 .963) is unrecorded in RESULTS_A.md; its results.csv has duplicated epochs 26-28 (resumed run), so the curve needs de-duplication before plotting.
4. `prepare_yolo_plate_detector.py` globs `*.jpg` only, so the plate detector used 181 of 2,021 labelled files. This is probably correct (the PNGs are pre-cropped plates whose box covers the whole image, which would distort a full-scene detector) but it is undocumented; manifest `image_count: 181` should state why.
5. RAM gate borderline because backend + Frigate are running (see above).
6. Track C: artifacts intact (`runs/C/eval/TEST_EVALUATED.lock` present, `track_c/results/qlora_full_c_v1_metrics.json` present). Test split already consumed once -> **must not be retrained/re-tested** on the same split.

### What must be supplied for Track A OCR (MANUAL; no login-free license-clear source found)

- Indian_LPR: academic data-sharing agreement with the authors.
- IEEE DataPort "VisionPlate ANPR" (Indian_ALPR_OCR_Dataset.zip, cropped plates) and "Indian License Plate Recognition Dataset (YOLO & OCR)" (36-class character crops): login required; verify license on page, download manually into `~/ml-assets/campus/datasets/IN-07/` and `IN-08/`.
- Or: hand-label plate text for the 1,840 IN-02 PNG crops (CC0) as `image_path,plate_text` CSV; machine OCR (EasyOCR/TrOCR) output is NOT acceptable as ground truth.
