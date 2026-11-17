# CVS-ACS: Complete Combined Audit, Dataset Catalog, Bug Plan & Roadmap (Zero-Loss Union)

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Target Site:** Punjab Engineering College (PEC), Chandigarh (`GATE_1`, `GATE_2`, `GATE_3`)  
**Architecture Mandate:** `OBSERVE -> ASSOCIATE -> CONTEXTUALIZE -> RECORD -> ALERT` (ML assists; human guards make all final gate decisions — no autonomous denial of access)

> **Note on Consolidation:** This document preserves **every point from both** our repo-grounded audit (`cvs_acs_project_status_and_roadmap.md`) and `deep-research-report.md` without deleting any items. Where `deep-research-report.md` assumed a module was unimplemented due to outdated docs, the **Verified Repo Reality** note is shown right alongside it so no work is duplicated.

---

## 1. Executive Summary & Work Remaining Estimates

| Perspective | Est. Completion | Est. Remaining Work | Basis |
| :--- | :--- | :--- | :--- |
| **Repo-Grounded Audit** | **~55–60% complete** | **~40–45% (~4–6 weeks)** | Counts already-built `backend/app/main.py` (`v0.6.0`, 10 routers), `frontend/` (`v0.5.0`), 27 audit-hardening commits, trained `YOLO11n`, and `Qwen3-1.7B` QLoRA |
| **Other Model (`deep-research-report.md`)** | **~30–40% complete** | **~60–70% (~12–15 person-weeks / 3–4 months)** | Assumes `frontend/`, JWT/auth, Track A detector, and Track C code are mostly unbuilt; splits remaining effort as ~40% code, ~40% data/ML, ~20% testing/deployment |

### Per-Workstream Status Matrix
| Workstream | Current Verified State | Est. Complete | Critical Blocker / Next Action |
| :--- | :--- | :--- | :--- |
| **Core Backend & DB Infrastructure** | 10 routers wired (`v0.6.0`), 14 Alembic tables on PostgreSQL 16 (`5433`), Mosquitto `2.1.2`, Frigate `0.18.0`, n8n `1.82+`, 20 audit regression checks | **75%** | Missing Phases 5–12 (Policy Engine, Delivery/Invoice APIs, Real WhatsApp, Security Review Queue, Audit Reason Codes) |
| **Guard & Admin Frontend** | React 19 + TS + Vite + Tailwind (`v0.5.0`) with `<LoginPage>`, `<ConnectionIndicator>`, `<FeedPage>`, `<InsidePage>`, `<MovementLogPage>`, `<VehicleHistoryPage>` | **55%** | Missing Delivery/Invoice Verification queue UI, Security Review Queue triage, and Reason-Code/Audit badges |
| **Track A: ANPR (Detector + OCR)** | `YOLO11n` detector trained (`0.824` test mAP50); `13,698`-crop `ocr_in_v1` built; `normalize_plate` + ambiguity matcher (`>=0.07` margin) | **65%** | OCR training failed CUDA OOM / RAM gate (`localsearch-3`); needs `KERAS_BACKEND=torch` run + PEC gate crops |
| **Track B: Invoice VLM Parsing** | Strict JSON schema + `Decimal` reconciler (`87.5%` arithmetic pass, `100%` line-item F1 on 32 synthetic docs) + n8n webhook stub | **35%** | Fix bipartite alignment (`B-S1-003`), run `Qwen3-VL-2B-Instruct` LoRA on 16 GB+ GPU (EC2 `g4dn.xlarge`) + consented Indian invoices |
| **Track C: Item Screening LLM** | `Qwen3-1.7B` QLoRA (`full_c_v1`) trained on synthetic taxonomy (`0.841` acc / `0.818` macro-F1), 21 deterministic policy rules | **70%** | **NO-GO for production** until retrained & calibrated on 500+ human-labeled real campus delivery items |
| **Integration, Testing & Ops** | 20 audit regressions pass; review harness at `46%` coverage; `3` E2E smoke pipelines | **45%** | Raise coverage to `90%`, wire Track B→C adapter, run 13 E2E scenarios, `SIMULATION_MODE`, CI/SAST, Locust load tests, Sentry/Grafana |

---

## 2. What Has Been Done (All Verified Points Combined)

### 2.1 Infrastructure, Database & Backend
* **Containerized Stack (`docker-compose.yml`, [README.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/README.md)):** PostgreSQL 16.15 (`5433`), Mosquitto MQTT `2.1.2` (`1883`), Frigate NVR `0.18.0` (`5000`/`8554`, Intel VAAPI iGPU), n8n `1.82+` (`5678`), RapidOCR + Tesseract 5.5, and `SETUP_REPORT.md`.
* **FastAPI Backend (`v0.6.0`, Python 3.14, port `8000`):** 10 routers wired in [backend/app/main.py](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/backend/app/main.py) (`auth`, `vehicles`, `owners`, `gates`, `lanes`, `observations`, `movements`, `presence`, `feed`, `resolutions`), plus `mqtt_manager` and `frigate_worker` lifecycle hooks and `/health`, `/health/db`, `/health/mqtt`, `/health/all`.
* **Database & Migrations:** 14 relational tables in SQLAlchemy 2.0 + Alembic migrations covering users, vehicle owners, vehicles, delivery vehicles, gates, access decisions, entry/exit logs, security alerts, delivery orders, invoices, invoice items, visitors, health checks, and observation events.
* **Phases Completed (Docs + Code):** Milestone 0 and Phases 1–4 (unit test counts cited in README: `11/11`, `15/15`, `20/20`, `20/20`), plus Phase 5A identity resolution.

### 2.2 Security & Adversarial Audit Hardening (27 Commits on `2026-10-13`)
* Staff bearer auth enforced on reads; `ADMIN` RBAC enforced on gate writes, generic ingestion, and raw MQTT debug buffer.
* Startup rejection of weak/placeholder `AUTH_SECRET_KEY`; HTTP 401 on non-ASCII bearer tokens; plate text/request bodies kept out of logs; Roboflow API key redacted from fetch errors.
* Hardened Frigate `0.18` `recognized_license_plate` parsing; prevented detector confidence from masquerading as OCR confidence; rejected `NaN`/`Infinity` confidences; filtered pedestrian detections; serialized per-event ingestion; blocked `TRUNCATE` on append-only tables; fixed Alembic `%` escaping in `DATABASE_URL`; added `health_checks` migration.

### 2.3 Guard Dashboard (`frontend/src/App.tsx`, `v0.5.0`)
* Hash-routed React 19 + TypeScript + Vite + Tailwind CSS app with `AuthProvider`, `useSession`, `<LoginPage>`, `<ConnectionIndicator>`, toast notifications, `<FeedPage>`, `<InsidePage>`, `<MovementLogPage>`, and `<VehicleHistoryPage>`.

### 2.4 Research Track (A, B, C)
* **Track A (ANPR):** `normalize_plate()` (Indian BH & State series) + `OpticalPlateMatcher` (`0%` false-match rate on 5 near-duplicate synthetic pairs with `>= 0.07` ambiguity margin vs `100%` for naive fuzzy). Trained **YOLO11n plate detector** (`20261012_detector_in_v1/full`, 100 epochs, 17 min on RTX 4050): **0.889 val mAP50 / 0.529 mAP50-95** (`n=115`), **0.824 test mAP50 / 0.440 mAP50-95** (`n=118`, 142 plates; weakest source `deepakat002` 1080p frames at R `0.70` vs `0.12` baseline). Zero-shot OCR on 1,840 IN-02 crops: LPRNet `0.922` format-valid, CCT-global `0.695`, European ONNX `0.613`.
* **Track B (Invoice Extraction):** Strict JSON Schema (`invoice_schema.json`), `InvoiceReconciler` (`Decimal` math), `FieldNormalizer`, `DeterministicValidator`, `HeuristicTextBaselineExtractor`, and n8n webhook stub (`POST /webhook/n8n-test`). Evaluated on 32 synthetic invoices + 6 adversarial cases: **100% schema-valid**, **87.5% arithmetic pass**, **100% line-item F1**.
* **Track C (Item Screening & Policy):** Decoupled perception from deterministic policy (`confidence < 0.70` or `None` on permitted items degrades to `REVIEW`; `ALERT` never degrades). Trained **Qwen3-1.7B + QLoRA** (`full_c_v1`, 251s, peak `3.77 GiB` VRAM) on `188 / 69 / 63` synthetic split (`191` families): **0.841 acc**, **0.818 macro-F1**, **0.0% invalid JSON** (vs lexical `0.365`/`0.445`, MiniLM kNN `0.540`/`0.406`, zero-shot Qwen3-1.7B `0.333`/`0.432`).

### 2.5 Testing & Documentation
* `scripts/test_audit_regressions.py` (20 `check_*` security/ingestion scenarios), `scripts/test_fastapi.py` (5 health/webhook endpoints), `scripts/test_e2e.py` (3 smoke pipelines), and `research_track/review/` (10 isolated review tests passing).
* Architecture/context docs: `PROJECT_ARCHITECTURE.md`, `context.md`, `SETUP_REPORT.md`, `research_track/MANIFEST.yaml`, `PROJECT_DIGEST.md`, `SETUP_RESULT.md`, `REVIEW_REPORT.md`, `OPEN_DECISIONS.md`.

---

## 3. Complete Combined Dataset & Model Catalog

### 3.1 Indian License Plates & Vehicle Tracking (Track A + Supplemental)
| Dataset | Size / Scope | License | Status / Role |
| :--- | :--- | :--- | :--- |
| [kedarsai/indian-license-plates-with-labels](https://www.kaggle.com/datasets/kedarsai/indian-license-plates-with-labels) | 181 images | CC0-1.0 | **Downloaded & used** in YOLO11n training |
| `prepared/plate_det_in_v1` (22 Kaggle + 6 Roboflow CC BY 4.0 sets) | 1,716 images (`1,483/115/118`) | Mixed OSS / CC BY 4.0 | **Built & used** for YOLO11n full run |
| `avinash-6` + `kp00011` (`prepared/ocr_in_v1`) | 13,698 real crops (`9,570/2,053/2,073`) | Apache-2.0 / MIT | **Built**, 0 plate-text overlap — **awaiting OCR training** |
| [sanchit2843/Indian_LPR](https://github.com/sanchit2843/Indian_LPR) (arXiv 2111.06054), arXiv 2207.06657, IEEE `IND-VNP` | Up to 16,192 images | Restricted / Manual | **Manual/withheld** — backup if `ocr_in_v1` underperforms |
| **DataCluster Indian Number Plates** (HuggingFace) | 15,000+ images (5,000 annotated) | Restrictive (academic/sample) | *From Report B* — backup if license cleared |
| **UFPR-ALPR** (~4,500) & **CCPD** (250K Chinese plates) | Generic ANPR | Research | *From Report B* — detector pretraining only (NOT Indian text) |
| **DataCluster Indian Vehicle (Auto)**, **BDD100K** (100K), **UA-DETRAC** (100K frames), **VeRi-776** / **VehicleID** | Vehicle detection & Re-ID | CC BY 4.0 / Research | *From Report B* — optional if cross-camera appearance Re-ID is needed |
| **Campus Gate Collection (To Collect)** | Target: ~200–3,000 PEC gate images (day/night, blur) | Internal / Consented | **Mandatory** for PEC production calibration |

### 3.2 Invoices, Receipts & Item Classification (Track B & C + Supplemental)
| Dataset | Size / Scope | License | Status / Role |
| :--- | :--- | :--- | :--- |
| [katanaml-org/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) | 500 annotated invoices (189 MB) | MIT | **Downloaded** — ready for Track B benchmarking |
| [naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) | ~1,000 receipts (2.2 GB) | CC-BY-4.0 | **Downloaded** — ready for Track B fine-tuning |
| **Divya52 Indian GST Invoices** (~2,000 synthetic Hindi/Kannada/English) | ~2,000 invoices | CC-BY-4.0 | *From Report B* — supplemental for Indian GST layouts |
| **SROIE 2019** (973 receipts), **FUNSD** (200 forms), **RVL-CDIP / IIT-CDIP** | Receipts & forms | CC-BY-4.0 / Research | *From Report B* — supplemental OCR/layout pretraining |
| `item_taxonomy_seed.csv` + Track B synthetic/adversarial fixtures | 320 item rows (191 families) + 38 invoice fixtures | Internal | **Used** in Track B/C synthetic benchmarks |
| **GroceryProducts-1200** / **GroZi-120** | Product text/images | Research | *From Report B* — supplemental for item text classification |
| **Real Consented Invoices & Campus Items (To Collect)** | 100+ Zomato/Swiggy/UPI invoices + 500+ real line items | Consented / Internal | **Mandatory** before Track B/C production sign-off |

### 3.3 Pretrained & Fine-Tuned Models
* **Track A:** `YOLO11n` (trained), YOLOv9 ONNX (`384/608/640`), YOLOv8 (alternative), `fast-plate-ocr` MobileViT-v2, `cct_s_v2_global.keras` (MIT, target for `KERAS_BACKEND=torch`), `PaddleOCR-VL` (0.9B, Python 3.12), `LPRNet` / `CRNN`, plus optional trackers (`Deep SORT`, `PCB`, `OSNet`).
* **Track B:** [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) + Receipt LoRA (requires 16 GB+ GPU; `Qwen2.5-VL-3B-Instruct` skipped; `Qwen2-VL` LoRAs incompatible), `LayoutLMv3`, `PP-StructureV3`, `RapidOCR`, `Tesseract 5.5`.
* **Track C:** [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) + `full_c_v1` QLoRA, `paraphrase-multilingual-MiniLM-L12-v2`, `BERT` (alternative classifier).

---

## 4. What Has to Be Rectified & Corrected

1. **Documentation vs. Codebase Drift:** Sync `README.md` Section 6 (Phases 5–16) and `PROJECT_DIGEST.md` with actual `backend/app/main.py` (`v0.6.0`) and `frontend/` (`v0.5.0`). Reconcile `item_taxonomy_seed.csv` count (`320` verified vs `321`/`300` in docs).
2. **Hardcoded `mock_whatsapp`:** `backend/app/main.py` directly imports `mock_whatsapp`; replace with an abstract WhatsApp provider interface (gating mock behind `SIMULATION_MODE=true`).
3. **Review Report Bugs (`REVIEW_REPORT.md` & `OPEN_DECISIONS.md`):**
   * `B-S1-003`: Replace greedy `align_line_items()` in Track B with deterministic optimal bipartite assignment + tie-breaking.
   * `B-S2-004`: Resolve comma-decimal locale ambiguity (`1,234`), handling fees, item-level discounts, and multi-page provenance.
   * `X-S1-001`: Build pure Track B→C adapter preserving `Decimal` quantity, `None` quantity, unit vocabulary, and line-item IDs.
   * `X-S2-002`: Align `research_track/db_draft/` and `research_track/frontend/` mocks with nullable confidence, `ReasonCodes`, and `policy_version`.
   * Low test coverage: Raise `research_track/review/` coverage from **46%** to **>= 90%**.
   * Repo hygiene (`I-S0-001`, `I-S2-002`): Ensure Git root stays scoped to repo and clean up >5 MB files in `research_track/frontend/node_modules/`.
4. **Local ML Training Blockers:**
   * Track A OCR hit CUDA OOM (detector held `2.9 / 5.7 GiB` VRAM) and RAM gate failure (`MemAvailable 4.31 GiB` due to GNOME `localsearch-3` holding `4.32 GiB`).
   * TF 2.21 CUDA fails locally; Track A OCR must run with `KERAS_BACKEND=torch` in the Python 3.12 venv (`~/ml-assets/campus/.venv-ml`).
5. **MQTT & Gate Direction Enforcement (from Report B):** Ensure Frigate events are treated as provisional until lane role or guard confirmation (`In`/`Out`) is recorded—never auto-log entry/exit without guard context.

---

## 5. Complete Bug & Quality Testing Plan (Combined Matrix)

Run the automated Python tester (`cvs_acs_bug_tester.py --repo-root . [--live]`) plus the full verification matrix below:

| Component | Test Cases & Commands | Expected Result | Severity |
| :--- | :--- | :--- | :--- |
| **Repo & Env Hygiene** | `python3 cvs_acs_bug_tester.py --repo-root .` | Flags doc drift, `mock_whatsapp`, `AUTH_SECRET_KEY`, `KERAS_BACKEND=torch`, RAM `<6 GiB` | **High** |
| **Audit Regressions** | `python3 scripts/test_audit_regressions.py` | All 20 `check_*` scenarios pass against scratch DB | **Critical** |
| **Vehicle / Gate API** | `pytest tests/` (CRUD + wrong auth on gate open/close) | Model persists; `401 Unauthorized` on bad/missing token | **High** |
| **MQTT Listener** | `mosquitto_pub` JSON payload to `frigate/events` | New provisional event created; duplicates & pedestrians suppressed | **High** |
| **Track A ANPR** | Known plate gallery + `deepakat002` 1080p frames | OCR text accurate; empty OCR returns `UNREADABLE` (`A-S1-001`) | **Medium** |
| **Track B Invoice OCR** | `curl -F "file=@test_invoice.jpg" http://localhost:8000/parse_invoice` | Strict schema valid; `Decimal` math & bipartite alignment pass | **High** |
| **Track C Policy Engine** | High-amount / restricted item / `is_uncertain=True` | Triggers `ALERT` or escalates `ALLOW` → `REVIEW` | **High** |
| **Guard Dashboard UI** | Selenium / Playwright UI test on login, queues, overrides | Displays pending lists; guard approve/override persists | **Medium** |
| **Load & Backpressure** | **Locust / JMeter**: 100 vehicles/min across 3 gates + slow OCR | No crash; `<2s` API response; no unbounded queue growth | **High** |
| **Failure Mode & Ops** | Simulate DB down / MQTT drop | Safe error code, DB retry/backoff, MQTT dead-letter queue | **High** |
| **Privacy / PII & SAST** | `ruff .`, `mypy .`, `bandit -r backend/`, face/PII OCR check | Zero lint/type/SAST blockers; no faces/PII stored or logged | **High** |

---

## 6. Unified Roadmap to Final Product (~4–6 Weeks Core / Up to 3 Months Full Pilot)

1. **Stage 1 — Audit Fix, Hygiene & CI (Days 1–4):**
   * Run `cvs_acs_bug_tester.py`, sync `README.md` & `PROJECT_DIGEST.md`, fix `B-S1-003` bipartite alignment, build Track B→C adapter, raise review coverage to `>= 90%`, and add GitHub Actions CI (`pytest`, `ruff`, `mypy`, `bandit`).
2. **Stage 2 — Track A OCR & Track B/C Real-Data Training (Weeks 1–2):**
   * Stop `localsearch-3` (`>= 6 GiB` free RAM), train Track A OCR (`cct_s_v2_global.keras`, `KERAS_BACKEND=torch`) on `prepared/ocr_in_v1` + 200+ PEC gate crops.
   * Provision EC2 `g4dn.xlarge` (16 GB T4), benchmark `Qwen3-VL-2B-Instruct` on `invoices-donut-data-v1` + `cord-v2`, and fine-tune on `cord-v2` + 100+ consented Indian/UPI invoices.
   * Collect & human-label 500+ real campus delivery items, retrain `Qwen3-1.7B` QLoRA, and calibrate confidence thresholds.
3. **Stage 3 — Production Backend & Delivery Pipeline (Weeks 2–4):**
   * Implement Roadmap Phases 5–12: Access Control Policy Engine, Entry/Exit & History APIs (`GET /logs`, `GET /vehicles/{plate}/history`), `POST /orders/process-invoice`, `DeliveryVerificationService`, live WhatsApp Business Cloud API provider, `/security/reviews` queue, and immutable `ReasonCode` audit logs.
   * Enforce lane/direction confirmation rules for provisional Frigate events.
4. **Stage 4 — Frontend, Load Testing, Hardening & Campus Pilot (Weeks 4–6+):**
   * Wire Delivery/Invoice Verification, Security Review Queue, and Reason-Code/Audit UI into `frontend/src/App.tsx` (Phase 16).
   * Execute all 13 E2E scenarios + `SIMULATION_MODE=true` (Phases 14–15), run Locust/JMeter 3-gate burst load tests, add MQTT DLQ, DB retries, Sentry/Grafana monitoring, HTTPS + rate limiting, and PII/face filtering.
   * Deploy shadow-mode pilot at PEC `GATE_1`, collect guard feedback, and roll out across `GATE_1`–`GATE_3`.
