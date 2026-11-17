# CVS-ACS: Project Status, Dataset & Training Audit, Bug Rectification, and Roadmap to Final Product

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Target Deployment:** Punjab Engineering College (PEC), Chandigarh (3 Perimeter Gates: `GATE_1`, `GATE_2`, `GATE_3`)  
**Architecture Mandate:** `OBSERVE -> ASSOCIATE -> CONTEXTUALIZE -> RECORD -> ALERT`

---

## 1. Executive Summary & Overall Completion

Based on a full audit of the repository (`main` branch, 27 commits), the project is **~55–60% complete** overall. Core backend infrastructure, database schemas, Frigate/MQTT ingestion, adversarial security hardening, Track A plate detection, and Track C synthetic item classification are built and verified. However, **Track A OCR fine-tuning**, **Track B invoice VLM fine-tuning**, **production delivery/WhatsApp/policy-engine routes**, and **end-to-end UI integration** remain incomplete or blocked.

| Workstream | Current Status | Est. Completion | Critical Blocker / Next Action |
| :--- | :--- | :--- | :--- |
| **Core Backend & DB Infrastructure** | 10 routers wired (`v0.6.0`), 14 Alembic tables, 20 audit regression checks | **75%** | Missing Phases 5–12 (Policy Engine, Delivery/Invoice APIs, Real WhatsApp, Security Review Queue) |
| **Guard & Admin Frontend** | React/TS/Vite (`v0.5.0`) with 4 views (`feed`, `inside`, `logs`, `history`) | **55%** | No delivery/invoice review UI, no alert triage/audit reason-code UI |
| **Track A: ANPR (Detector + OCR)** | YOLO11n detector trained (`0.824` test mAP50); OCR training blocked | **65%** | OCR training failed CUDA OOM / RAM gate (`localsearch-3`); needs `KERAS_BACKEND=torch` run |
| **Track B: Invoice VLM Parsing** | Deterministic schema/reconciler built (`87.5%` arithmetic pass on 32 synthetic docs) | **35%** | No VLM fine-tuning run yet; needs 16 GB+ GPU (EC2 `g4dn.xlarge`) + consented real invoices |
| **Track C: Item Screening LLM** | Qwen3-1.7B QLoRA trained on synthetic taxonomy (`0.841` acc / `0.818` macro-F1) | **70%** | **NO-GO for production** until trained/calibrated on human-labeled real campus delivery items |
| **Integration, Testing & Ops** | 20 audit regressions pass; review harness at `46%` coverage | **45%** | Raise coverage to `90%`, wire Track B→C adapter, run 13 E2E scenarios & `SIMULATION_MODE` |

---

## 2. What Has Been Done (Verified Implementation)

### 2.1 Production Backend, Infrastructure & Security Hardening
* **Infrastructure Stack (`docker-compose.yml`, [README.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/README.md)):**
  * **FastAPI Backend (`v0.6.0`, Python 3.14, port `8000`):** 10 routers wired in [backend/app/main.py](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/backend/app/main.py) (`auth`, `vehicles`, `owners`, `gates`, `lanes`, `observations`, `movements`, `presence`, `feed`, `resolutions`), plus `mqtt_manager` and `frigate_worker` lifecycle hooks.
  * **PostgreSQL 16.15 (port `5433`):** 14 relational tables managed via SQLAlchemy 2.0 and Alembic migrations.
  * **Ingestion & Automation:** Mosquitto MQTT 2.1.2 (port `1883`), Frigate NVR 0.18.0 (ports `5000`/`8554`, Intel VAAPI), RapidOCR + Tesseract 5.5, and n8n 1.82+ (port `5678`).
* **Adversarial Audit Hardening (27 commits on `2026-10-13`, [scripts/audit\_regressions/](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/tree/main/scripts/audit_regressions)):**
  * Enforced staff bearer auth on reads, `ADMIN` role on gate writes/generic ingestion/raw MQTT debug buffer, startup rejection of placeholder `AUTH_SECRET_KEY`, and HTTP 401 on non-ASCII bearer tokens.
  * Hardened Frigate 0.18 `recognized_license_plate` parsing, prevented detector confidence from masquerading as OCR confidence, rejected `NaN`/`Infinity` confidences, filtered pedestrian detections, serialized per-event ingestion, and blocked `TRUNCATE` on append-only tables.
  * Fixed Alembic `%` escaping in `DATABASE_URL` and added `health_checks` migration so fresh DBs pass `alembic check`.
* **Guard Dashboard ([frontend/src/App.tsx](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/frontend/src/App.tsx), `v0.5.0`):**
  * React 19 + TypeScript + Vite + Tailwind CSS hash-routed console with `<LoginPage>`, `<ConnectionIndicator>`, `<FeedPage>` (live feed), `<InsidePage>`, `<MovementLogPage>`, and `<VehicleHistoryPage>`.

### 2.2 Research Track (ML Models & Pipelines)
* **Track A — ANPR & Plate Matching ([research\_track/track\_a/IMPLEMENTATION\_REPORT.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/research_track/track_a/IMPLEMENTATION_REPORT.md)):**
  * Built Indian BH & State plate normalizer (`normalize_plate()`) and `OpticalPlateMatcher` with ambiguity margin `>= 0.07` (`0%` false-match rate on 5 near-duplicate synthetic pairs vs `100%` for naive fuzzy matching).
  * Trained **YOLO11n plate detector** (`20261012_detector_in_v1/full`, 100 epochs, 17 min on RTX 4050): achieved **0.889 mAP50 / 0.529 mAP50-95** on val (`n=115`) and **0.824 mAP50 / 0.440 mAP50-95** on test (`n=118`, 142 plates).
* **Track B — Invoice Extraction & Reconciliation ([research\_track/track\_b/IMPLEMENTATION\_REPORT.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/research_track/track_b/IMPLEMENTATION_REPORT.md)):**
  * Built strict JSON Schema (`invoice_schema.json`), `InvoiceReconciler` (`Decimal` arithmetic), `FieldNormalizer`, `DeterministicValidator`, and `HeuristicTextBaselineExtractor`.
  * Evaluated on 32 synthetic invoices + 6 adversarial cases: **100% schema-valid**, **87.5% arithmetic pass**, **100% line-item F1**.
* **Track C — Item Screening & Policy Engine ([research\_track/finetune/RESULTS\_C.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/research_track/finetune/RESULTS_C.md)):**
  * Decoupled perception from deterministic policy (`confidence < 0.70` or `None` on permitted items degrades to `REVIEW`; `ALERT` never degrades).
  * Trained **Qwen3-1.7B + QLoRA** (`full_c_v1`, 251s, peak `3.77 GiB` VRAM) on 188 train / 69 val / 63 test synthetic rows (`191` brand/template families): achieved **0.841 accuracy** and **0.818 macro-F1** (`0.0%` invalid JSON), outperforming lexical (`0.365` / `0.445`), MiniLM kNN (`0.540` / `0.406`), and zero-shot Qwen3-1.7B (`0.333` / `0.432`).

---

## 3. Complete Dataset & Training Audit

### 3.1 Datasets Inventory
| Dataset / Source | Track | Size / Count | License | Current Status |
| :--- | :--- | :--- | :--- | :--- |
| [kedarsai/indian-license-plates-with-labels](https://www.kaggle.com/datasets/kedarsai/indian-license-plates-with-labels) | Track A (Det) | 181 images | CC0-1.0 | **Downloaded & used** in detector training |
| `prepared/plate_det_in_v1` (22 Kaggle + 6 Roboflow CC BY 4.0 sets) | Track A (Det) | 1,716 images (`1,483 / 115 / 118`) | Mixed OSS / CC BY 4.0 | **Built & used** for YOLO11n full run (`deepakat002` 1080p frames remain hardest: R `0.70`) |
| `avinash-6` + `kp00011` (`prepared/ocr_in_v1`) | Track A (OCR) | 13,698 real crops (`9,570 / 2,053 / 2,073`) | Apache-2.0 / MIT | **Built**, 0 plate-text overlap; **awaiting OCR training run** |
| [sanchit2843/Indian_LPR](https://github.com/sanchit2843/Indian_LPR) (arXiv 2111.06054) | Track A | 16,192 images (withheld) | Restricted | **Manual/withheld** by authors (only 2.5 MB metadata) |
| arXiv 2207.06657 & IEEE DataPort (`Indian LPR`, `IND-VNP`) | Track A | Varies | Restricted / Login | **Manual** — not downloaded; optional if `ocr_in_v1` + PEC gate footage suffice |
| [katanaml-org/invoices-donut-data-v1](https://huggingface.co/datasets/katanaml-org/invoices-donut-data-v1) | Track B | 500 annotated invoices (189 MB) | MIT | **Downloaded** to `~/ml-assets/campus/`; **not yet trained/evaluated** |
| [naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) | Track B | ~1,000 receipts (2.2 GB) | CC-BY-4.0 | **Downloaded** to `~/ml-assets/campus/`; **not yet trained/evaluated** |
| Synthetic Invoices + Adversarial Fixtures | Track B | 32 + 6 fixtures | Internal | **Evaluated** with deterministic baseline only |
| `item_taxonomy_seed.csv` | Track C | 320 rows (191 families, 7–8 codes) | Internal | **Used** for `full_c_v1` QLoRA (`188 / 69 / 63` split) |
| **Missing Real-World Datasets (Required for Production)** | All | Target: 200+ PEC gate crops, 100+ consented Indian/UPI invoices, 500+ real campus line items | Consented / Internal | **Not yet collected** — mandatory before production sign-off |

### 3.2 Models Inventory
| Model | Track | Local Staging / Status |
| :--- | :--- | :--- |
| YOLOv9 Plate Detectors (`384`, `640`, `608` ONNX) + `YOLO11n` | Track A | `YOLO11n` trained & saved; ONNX models staged (`44.2 MB`) |
| `fast-plate-ocr` MobileViT-v2 ONNX & `cct_s_v2_global.keras` (MIT) | Track A | Staged; zero-shot CCT-global `0.695` format-valid on IN-02; **fine-tuning blocked** |
| `PaddleOCR-VL` (0.9B) | Track A | Staged (`2.0 GB`); requires Python 3.12 venv |
| [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) + Receipt LoRA | Track B | Staged (`4.0 GB` + `23 MB`); **not executed** (needs 16 GB+ VRAM / EC2) |
| `Qwen2.5-VL-3B-Instruct` | Track B | **Skipped** (30 GB disk cap + research-only license) |
| `chai1me` / `saliousk` Qwen2-VL LoRAs | Track B | Model cards only; **incompatible** with Qwen3-VL |
| [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) + `full_c_v1` QLoRA | Track C | Staged (`3.8 GB`); **trained & evaluated** on synthetic split |
| `paraphrase-multilingual-MiniLM-L12-v2` | Track A/C | Staged (`477 MB`); evaluated as Track C kNN baseline (`0.540` acc) |

---

## 4. What Has to Be Rectified & Corrected

1. **Documentation vs. Codebase Drift (High Priority):**
   * `README.md` Section 6 only checks off Milestone 0 and Phases 1–4, and `research_track/PROJECT_DIGEST.md` still lists the React dashboard as `(planned)` and Phases 5B/5C+ as open—even though `backend/app/main.py` (`v0.6.0`) already wires 10 routers (`feed`, `resolutions`, `lanes`, `movements`, `presence`) and `frontend/` (`v0.5.0`) is built.
   * `research_track/track_c/IMPLEMENTATION_REPORT.md` claims `321` taxonomy rows and `SETUP_RESULT.md` mentions `300` unique lines, while `REVIEW_REPORT.md` verified `320` rows.
2. **Mocked WhatsApp Integration in Production Entrypoint:**
   * `backend/app/main.py` imports `backend.app.whatsapp.mock` (`mock_whatsapp`) directly without an abstract provider interface or live WhatsApp Cloud API / Twilio adapter.
3. **Open Review Bugs & Architectural Gaps ([research\_track/review/REVIEW\_REPORT.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/research_track/review/REVIEW_REPORT.md) & [OPEN\_DECISIONS.md](https://www.google.com/search?q=https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System/blob/main/research_track/review/OPEN_DECISIONS.md)):**
   * **Track B Line-Item Alignment (`B-S1-003`):** `align_line_items()` uses greedy scoring instead of deterministic optimal one-to-one bipartite assignment with defined duplicate-description tie-breaking.
   * **Track B Locale Ambiguity (`B-S2-004`):** Comma-decimal strings (e.g., `1,234`), handling fees, item-level discounts, and multi-page source provenance need an explicit policy decision.
   * **Cross-Track Adapter (`X-S1-001`):** No production-ready Track B → Track C adapter exists that preserves `Decimal` quantity, `None` quantity, unit vocabulary, and line-item IDs.
   * **Schema & Mock Divergence (`X-S2-002`):** `research_track/db_draft/` and `research_track/frontend/` mocks diverge from nullable confidence, stable `ReasonCodes`, `policy_version`, and audit trace requirements.
   * **Low Review Test Coverage:** `research_track/review/` coverage sits at **46%** (target: **90%**).
   * **Git Root & Large `node_modules` (`I-S0-001`, `I-S2-002`):** Workspace Git root previously resolved to `/home/kirat`, and `research_track/frontend/node_modules/` contained files >5 MB.
4. **Track A OCR Training Environment Blockers:**
   * Concurrent OCR smoke test hit **CUDA OOM** (detector held `2.9 GiB` of `5.7 GiB` VRAM on RTX 4050).
   * Subsequent run failed the RAM gate (`MemAvailable = 4.31 GiB`) because GNOME `localsearch-3` held `4.32 GiB`.
   * TensorFlow 2.21 cannot load CUDA locally; OCR training must explicitly set `KERAS_BACKEND=torch` and initialize from `cct_s_v2_global.keras` with 11-slot `0-9A-Z_` config.

---

## 5. Detailed Future Plan: From Current State to Final Product

### Phase 1 — Immediate Rectification & Code Hygiene (Est. 2–3 days)
* Run `cvs_acs_bug_tester.py` across the repo to establish a baseline of all static, contract, and environment issues.
* Sync `README.md` (Section 6) and `PROJECT_DIGEST.md` with actual `backend/app/main.py` (`v0.6.0`) and `frontend/` (`v0.5.0`) capabilities; reconcile `item_taxonomy_seed.csv` row count (`320`).
* Finalize `OPEN_DECISIONS.md` items: implement deterministic Hungarian/bipartite line-item alignment in Track B, lock comma-decimal locale rules, build the pure Track B→C `Decimal`/null adapter, and raise `research_track/review/` test coverage from `46%` to `>= 90%`.

### Phase 2 — Complete ML Training & Real-Data Calibration (Est. 1–2 weeks)
* **Track A (ANPR OCR):** Stop `localsearch-3` / free system RAM (`>= 6 GiB` available), ensure no other GPU process holds VRAM, and train `cct_s_v2_global.keras` with `KERAS_BACKEND=torch` on `prepared/ocr_in_v1` (`9,570 / 2,053 / 2,073`). Add hard-negative small-plate crops (like `deepakat002` 1080p frames) and 100+ real PEC gate frames to push test recall from `0.796` toward `>= 0.90`.
* **Track B (Invoice VLM):** Provision an EC2 `g4dn.xlarge` (16 GB T4) or equivalent cloud GPU, benchmark zero-shot `Qwen3-VL-2B-Instruct` on `invoices-donut-data-v1` + `cord-v2`, then fine-tune QLoRA on `cord-v2` + 100+ consented Indian delivery invoices (Zomato/Swiggy/Blinkit/Amazon/courier slips).
* **Track C (Item Screening):** Collect 500+ real campus delivery line items, label by human security reviewers, retrain `Qwen3-1.7B` QLoRA, and calibrate temperature/confidence thresholds so `is_uncertain=True` safely escalates ambiguous `ALLOW` predictions to `REVIEW`.

### Phase 3 — Production Backend & Delivery Pipeline (Est. 1.5–2 weeks)
* **Access Control & Policy Engine (Roadmap Phase 5):** Integrate Track A (YOLO11n + trained OCR + ambiguity matcher) and Track C policy rules (`ALLOW` / `REVIEW` / `ALERT` + `ReasonCodes`) into `backend/app/services/`.
* **Entry/Exit & History APIs (Phase 6):** Verify/complete `GET /logs` and `GET /vehicles/{plate}/history` against live movement records.
* **Delivery & Invoice Pipeline (Phases 7–9):** Implement `POST /orders/process-invoice` and `DeliveryVerificationService` wiring n8n webhooks → Track B VLM extractor → Track C item screener → PostgreSQL (`delivery_orders`, `invoices`, `invoice_items` with `checkfirst=True` enum migrations).
* **Real WhatsApp Provider (Phase 10):** Abstract `backend/app/whatsapp/` behind a provider interface, keeping `mock_whatsapp` for `SIMULATION_MODE=true` / offline tests and adding a live WhatsApp Business Cloud API adapter.
* **Security Review Queue & Auditability (Phases 11–12):** Implement `/security/reviews` queue endpoints and immutable `ReasonCode` + `policy_version` audit logging.

### Phase 4 — Frontend Integration, E2E & Pilot Deployment (Est. 1–1.5 weeks)
* **Guard & Admin Dashboard (Phase 16):** Add Delivery/Invoice Verification tab, Security Review Queue (`/security/reviews`) triage actions, and Reason Code / Audit Trail badges to `frontend/src/App.tsx`.
* **Simulation & Full E2E Verification (Phases 14–15):** Implement `SIMULATION_MODE=true` replay of H.264 gate streams and mock WhatsApp invoices; expand `scripts/test_e2e.py` to cover all 13 end-to-end scenarios (beyond the current 3 health/smoke pipelines).
* **PEC Campus Pilot:** Deploy at `GATE_1` (shadow mode first, comparing automated `ALLOW`/`REVIEW`/`ALERT` against manual guard logs) before enabling live alerts across `GATE_1`–`GATE_3`.

---

## 6. How Much Work Is Left? (Effort Summary)

* **Total Remaining Effort:** **~4 to 6 weeks** of focused engineering + ML work (roughly **40–45% of total project scope** remaining).
* **Biggest Time Sinks:**
  1. Collecting & labeling real PEC gate plates, consented Indian invoices, and campus line items (~1–1.5 weeks).
  2. Training & calibrating Track A OCR + Track B Qwen3-VL on cloud/free GPU (~1 week).
  3. Building & testing the Delivery/Invoice + Security Review Queue + Real WhatsApp backend & frontend flows (~2 weeks).

---

## 7. Ready-to-Use Handoff Prompt (for Antigravity / Gemini 3.5 Flash)

If you execute the next steps locally in Antigravity, you can paste this prompt directly:

> "Inspect the repository `CVS-ACS--Campus-Vehicle-Security-Access-Control-System`. First, run `python3 cvs_acs_bug_tester.py --repo-root .` and report all failures. Second, fix the Track B `align_line_items()` greedy matching bug to use deterministic optimal bipartite assignment, add the pure Track B→C `Decimal`/null adapter, and raise `research_track/review/` pytest coverage above 90%. Third, verify free RAM (`>= 6 GiB`, stopping `localsearch-3` if needed) and run Track A OCR training using `KERAS_BACKEND=torch` initialized from `cct_s_v2_global.keras` on `prepared/ocr_in_v1`."
