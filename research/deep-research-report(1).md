# CVS-ACS Project Audit and Roadmap

The **Campus Vehicle Security & Access-Control System (CVS-ACS)** is a research-driven application to manage vehicle entry/exit at a college campus.  It uses 3 gate cameras (Gate1–Gate3) feeding into a central server (FastAPI + PostgreSQL) via Mosquitto MQTT.  Key features include vehicle/owner registries, movement history, invoice/receipt processing, and a human-supervised security dashboard.  The system is explicitly designed so that **machine learning only assists** (e.g. plate/vehicle recognition); **human guards make all final gate decisions** (no autonomous denial of access).  The existing architecture (as documented) includes: camera perception (via Frigate + YOLO), MQTT ingestion, FastAPI backend, database migrations, and a planned React dashboard.

## WHAT_HAS_BEEN_DONE (Completed Work)

- **Infrastructure & Stack:** The repo includes a fully containerized environment with **Docker-Compose** orchestration of all services, including FastAPI server, PostgreSQL database, Mosquitto MQTT broker, and Frigate NVR.  Base setup scripts and a `SETUP_REPORT.md` confirm service startup (likely via `docker-compose up`).

- **Database & Backend:** Core data models for vehicles, owners, gates, and audit logs are implemented in SQLAlchemy ORM with Alembic migrations.  Phase 1–3 (schema design, vehicle registry APIs, gate registry APIs) appear complete, as indicated by 11/11, 15/15, 20/20 unit tests claimed in README.  The repository includes `backend/` code and `alembic/` folders for migrations.  (Note: we have not executed these tests, but they are present.)

- **Frigate + Camera Ingestion:** A Frigate-based LPR pipeline is set up for all gates. Frigate uses a YOLOv9 license-plate detector plus PaddleOCR for text. Frigate publishes detection events (including plate text) over MQTT, and there are scripts (e.g. an MQTT subscriber) to ingest these into the FastAPI service.  Phase 4 (Frigate + MQTT) is reportedly completed with 20/20 tests.  We see configuration files in `backend/` that subscribe to MQTT topics and process “vehicle detected” or “plate read” events.

- **Invoices & OCR (Research Track B):** The architecture includes a WhatsApp/n8n workflow for delivery invoices (images) to be sent to a FastAPI OCR endpoint. The `n8n/` folder suggests plans for receiving invoice images via a webhook. The backend has placeholder code for parsing invoices via OCR (RapidOCR, Tesseract).  This is partly implemented (n8n workflows present), but *not yet fully trained or integrated* into a verification pipeline.  Preliminary invoice parsing scripts exist in `research_track/`.

- **Testing & Scripts:** There are smoke/e2e tests and health-check scripts in `scripts/`, likely to verify API endpoints, database connectivity, and Frigate ingestion.  The README lists E2E and OCR tests, MQTT health-check scripts. These indicate parts of the system can be automatically validated, although actual test outputs are not shown in code.

- **Documentation:** The repo contains `PROJECT_ARCHITECTURE.md` and `context.md` outlining the intended system and development context. The architecture doc describes the 3-gate setup, Frigate/MQTT ingestion, FastAPI core, and future components (e.g. invoice processing). This confirms our understanding of what was planned.

**Evidence:** Code files (models, APIs, scripts) are present in `backend/` and `scripts/`. The existence of Alembic migrations implies model definitions. The README and architecture docs assert completion of Phases 1–4. For example, Frigate’s YOLOv9 LPR and PaddleOCR are specifically mentioned in README (current LPR baseline). In summary, the core “data pipeline” (camera→Frigate→MQTT→FastAPI→DB) is in place, with functioning registries and audit logging.

## WHAT_HAS_TO_BE_DONE (Remaining Work)

- **ANPR Pipeline (Track A)** – *Not yet production-grade.* Frigate’s built-in LPR must be benchmarked and likely fine-tuned on campus data.  We need to collect and annotate Indian license-plate images (both day/night, many angles) and train a dedicated plate detector/recognizer.  This includes: extracting license-plate crops, training YOLOv9/YOLOv8 for plate bounding boxes, and fine-tuning PaddleOCR (or another OCR) for Indian scripts/format.  Currently, license matching simply passes Frigate’s output to an owner registry lookup.  Accuracy may be low without customization.  The project should leverage existing datasets to bootstrap (see “DATASETS_AND_MODELS” section). Work includes: evaluating Frigate’s plate text output vs ground truth, integrating a “confidence” measure, and handling errors (e.g. partial or noisy plate reads). The code for this is minimal so far (essentially pass-through), so a lot of development is needed here.

- **Invoice/Receipt Extraction (Track B)** – *Partially started.* The n8n trigger and FastAPI OCR endpoint exist, but the actual extraction of fields (order ID, vendor, total, items) and matching logic must be implemented.  Action items: train or configure an OCR/document parser on Indian invoices (GST format). Develop rules (or use NLP models) to extract order details. Then integrate with backend to verify a delivery against an expected order (by user/hostel data). Also implement de-duplication and time-window checks. Finally, wire this into the guard dashboard (e.g. a “Pending Verifications” queue). The dataset exists on HuggingFace (synthetic Indian GST invoices, ~8K images, CC-BY). We should use it plus real collected invoices for training/evaluation.

- **Item Classification & Policy (Track C)** – *Planned future.* After extracting invoice line items, classify them (e.g. food, stationery, prohibited, etc.) to flag policy violations. This likely uses a pretrained language model (or CNN for images) with custom fine-tuning. No code exists yet; planning needed. Also, implement a “policy engine” to output ALLOW/REVIEW/ALERT with reasons. 

- **React Guard Dashboard** – *Unimplemented.* The architecture includes a web dashboard to show “known vehicles”, “unknown vehicles”, “verification queue”, and real-time alerts. The `frontend/` folder exists (React, Vite, Tailwind) but needs actual pages and API integration. Critical tasks: connect to FastAPI endpoints for vehicle lists, show live camera feeds or snapshots, and allow guards to confirm/override events. There are no references to a running frontend in tests, so this is a major unfinished area.

- **Authentication & Authorization:** We assume guards need secure login and role-based access (e.g. admin vs guard). We did not see any JWT or auth logic in the partial code. Likely, user/guard accounts and permissions must be implemented.

- **MQTT & Gate Logic:** Currently, Frigate events are ingested regardless of direction. We need to enforce *lane roles* or guard confirmation for entry vs exit. This might mean assigning each camera a direction (entry/exit) or asking guard to press “In/Out” after alert. The code must incorporate this logic (e.g. ignoring plate reads until guard sets direction). The architecture doc warns to not automatically log entry/exit events. This suggests code changes to treat all Frigate events as provisional until human-approved.

- **Error Handling & Data Quality:** Review exception handling in MQTT listeners, image processing. Ensure misreads or network errors don’t crash the service. Build retry logic for database operations.

- **Security & Privacy:** Ensure camera feeds and data are secured. No open source of personal data. The system uses campus CCTV, so face recognition or PII should not be processed/stored without consent. Document data retention policies for plates/invoices. Add API rate limits or auth to protect endpoints. Possibly add HTTPS and firewall configuration (but that’s infra beyond code).

- **Reliability & Ops:** Set up proper health endpoints, logging and monitoring (e.g. log unanswered MQTT messages, dead-letter queue). We saw health-check scripts; ensure they cover all critical services. Prepare for real-time loads: can Postgres and Python handle peak gate traffic (e.g. many cars at once)? Perhaps simulate loads (discussed below).

**Summary:** The core pipeline exists but is largely untested on real data. The missing pieces are mainly in ML model training (ANPR, OCR), frontend UI, and robust operational logic (authentication, direction, error handling).

## DATASETS_AND_MODELS (Data and Pretrained Models)

We should **reuse existing datasets/models** rather than start from scratch, especially for CV/OCR. Below are key candidates (open datasets or well-known corpora):

- **Indian License Plates:**  
  - **DataCluster Indian Number Plates** (HuggingFace) – *15,000+ images (5,000 annotated)* with bounding-boxes and plate text. (Sample subset available; full set requires license). CC license on sample is restrictive (no commercial use) but it’s CC-BY for licensing inquiry. Ideal for detector+OCR.  
  - **Kaggle Datasets:** (If accessible) e.g. “Indian vehicle number plate YOLO annotation” (1,500 images) – mostly CC BY-NC-ND. Useful for validation but not to redistribute models.  
  - **Roboflow / DIY:** If online data is insufficient, plan to capture/annotate ~3K campus images (day/night, motion blur).  
  - **General ANPR Benchmarks:** UFPR-ALPR (~4,500 images), CCPD (250K Chinese plates, useful for detection but NOT for Indian text) – as supplement for generic detector training only.  
  - **OCR Text:** Use fine-tuned PaddleOCR on Indian plate templates. Possibly augment by synthetically overlaying fonts. Pretrained PaddleOCR and RapidOCR models (available in PyPI) will serve as a start.

- **Vehicle Detection/Tracking:**  
  - **DataCluster Indian Vehicle (Auto)** – 8,000+ images of Indian autos (object detection, CC BY4.0). Use for detecting vehicles entering/exiting. Note: only covers “auto” (small vehicles) class, so not all vehicles. Look for similar: DataCluster may have other “Car” or “Bus” subsets.  
  - **BDD100K (Berkeley)** – 100K driving images from US, with 1M+ annotated objects. Rich variety (cars, trucks, pedestrians). License open (research use). Use for pretraining a vehicle detector/tracker.  
  - **UA-DETRAC** – Traffic dataset (100k frames video of highway traffic) for detection/tracking (license CC BY 4.0 via Roboflow). Use for tracking algorithms or to benchmark cross-camera tracking.  
  - **VeRi-776 / VehicleID** – ReID datasets (5K vehicles, 50K images) for multi-camera tracking logic (though campus gates may only have 3 cameras). Could help tune appearance-based matching if needed.  
  - **Highway/City Datasets:** (Optional) Cityscapes, KITTI, etc. not specific to India but useful for base models.

- **Invoice/Receipt OCR:**  
  - **Divya52 Indian GST Invoices** – ~2,000 synthetic Indian invoices (imagefolder, CC BY 4.0). Contains diverse Hindi/Kannada/English GST fields. Good for initial training of an invoice parser.  
  - **SROIE 2019 (ICDAR)** – ~973 annotated receipts (Malaysia, English) for key-value extraction (cc-by-4.0). Provides examples of line-item text, totals. Helps general OCR + field extraction pipeline.  
  - **CORD (Clova OCR)** – 1,000+ Indonesian receipts (images + bounding-box+text annotations, CC BY 4.0). Contains layout of items, totals, totals. Useful for OCR and semantic parsing, even if language differs.  
  - **FUNSD (Form Understanding)** – 200 scanned forms (English) with layout/field relations. Helpful for designing invoice OCR (though not specific to invoices).  
  - **RVL-CDIP / IIT-CDIP** – large invoice/receipt corpora (mostly corporate), for pretraining text recognition or layout analysis.  
  - **New Data Collection:** The team should collect real Zomato/Swiggy invoice images (with consent) from faculty in lab to train/test in-house. This is crucial since public datasets may not match actual formats.

- **Product Classification (Line Items):**  
  - If we need to classify grocery/food items from text: consider **GroceryProducts-1200** (NUS), **GroZi-120**, or simpler – scrape text lists. Often item names are short, so a domain-specific text classifier (e.g. fine-tuned BERT with some manual labels) may suffice. Data: compendiums of common items.

- **Pretrained Models to Reuse:**  
  - **YOLO family:** Ultralytics YOLOv8/v9 for object detection. Use pretrained on COCO as base, fine-tune on vehicle/plate datasets. (YOLOv9 introduces PGI/GELAN for efficiency.) We should experiment with both YOLOv9 (lightweight, fast) and YOLOv8 (more mature and flexible).  
  - **PaddleOCR / RapidOCR:** These support English/Hindi text. PaddleOCR v3 has strong multi-language support and fine-tuning guides. RapidOCR (MIT license) is a simple pip-installable model for quick results. Tesseract (open source) as a fallback. We should benchmark all three on our plate/invoice images.  
  - **LPRNet or CRNN:** Classic end-to-end ANPR recognizer (not bounding boxes) – worth testing for cropped plates, but may have licensing issues.  
  - **Tracker/Re-ID:** For cross-camera tracking, consider Deep SORT (open source tracker) and pre-trained ReID embeddings (e.g. PCB, OSNet). Not essential initially, but existing code (OpenCV trackers or Sort) can join gate1 exit to gate2 entry.  
  - **Document Layout/OCR Models:** LayoutLMv3 or GraphFormers trained on receipts/invoices could help structured parsing. Paddle OCR’s PP-StructureV3 (for text+layout understanding) is promising for documents.  
  - **Language Models:** For invoice field parsing (e.g. extracting JSON from raw text), a fine-tuned LLM (like Mistral or LLama-2 medium) could assist. Alternatively, rule-based field matching might suffice.

**Licenses & Compute:** All above datasets are non-private (CC-BY or free). DataCluster sets require licensing for full commercial use, so plan is either academic prototype or use sample subsets.  Pretrained models (YOLO, PaddleOCR) are open-weights or permissive.  Compute: Fine-tuning YOLO may need GPU hours (use existing weights to minimize). PaddleOCR fine-tune is modest (<5k samples as recommended). Model serving can likely run on a decent GPU-enabled server (4–8GB GPU memory for YOLO inference).

**Implementation Recommendations:**  
- **Dataset Creation:** Merge and harmonize: e.g. combine Kaggle Indian-plates (if license allows) with DataCluster sample to train plate detector. Combine BDD100K with campus car photos for vehicle detector. Use SROIE+Divya GST+CORD for invoice-ocr training with domain-specific fine-tuning.  
- **Evaluation:** Hold out separate test sets (e.g. 20% of campus-collected images) to evaluate end-to-end accuracy (plate → registry match, invoice OCR → correct fields). Metrics: plate-ANPR accuracy, detection precision/recall, OCR character/field error rates.  
- **Continuous Monitoring:** Log predictions and confidences; if guard overturns a read, flag for model retraining.  

## BUG_TESTER (Testing Plan)

A comprehensive test plan must cover unit, integration, regression, E2E, and stress scenarios. Key areas:

- **Unit Tests (Backend):** For each API endpoint (FastAPI), ensure correct responses for valid/invalid inputs (e.g. vehicle registration CRUD, gate status updates, invoice submission). Use Pytest to run existing tests and add where missing. E.g. test database models via in-memory SQLite, validate Pydantic schemas reject bad data.

- **MQTT Ingestion:** Simulate Frigate events by publishing fake MQTT messages to the broker (e.g. JSON payloads from Frigate). Verify the subscriber service processes them, creates pending vehicle events, and triggers appropriate entries in the database. Test edge cases: malformed message, missing fields.

- **OCR & NLP Pipeline:** Unit-test OCR components by feeding known sample images (static receipts, plates) and comparing extracted text/fields to expected. Use a small gallery of labeled images (few Malaysian/Indian receipts, plates). Confirm text normalization (remove noise, handle Hindi numerals) works.

- **Integration/E2E Tests:** Script interactions across subsystems. For example:
  1. **Plate Detection E2E:** Place a car with a known plate at Gate1 (or use video frames). Confirm Frigate publishes event, FastAPI fetches/reads the plate text (could require mocking OCR), and an “entry request” appears in the database with correct vehicle owner ID (if registered) or in the “Unknown Vehicles” queue.  
  2. **Invoice Verification:** Post a test invoice image to the FastAPI endpoint (with n8n orchestrator simulation). Validate that fields (order_id, amount) are parsed, matched against a dummy expected order, and marked as VERIFIED/REJECTED.  
  3. **User Interface:** If a prototype dashboard exists, use Selenium or similar to ensure the guard can log in, see queues, and approve an event.

- **Regression Tests:** Whenever code changes (e.g. new model, updated business logic), rerun core tests: vehicle registry, gate open/close, invoice handling. Use CI (GitHub Actions) to automate.

- **Performance/Load Testing:** Simulate peak loads (e.g. 3 gates with vehicles arriving every few seconds, many MQTT messages). Tools: Locust or JMeter to send MQTT payloads or API calls. Monitor CPU, DB queries, memory. Ensure no memory leaks or unbounded queue growth. Also test slower OCR (cloud or GPU) to not block pipeline: simulate backlog.

- **Security Tests:** Attempt unauthorized API calls to ensure auth is required (if implemented). Test SQL injection / input validation (e.g. malicious plate string). Use static analyzers (bandit, etc.) on Python code. Check that no camera feed URLs or PII leak in logs.

- **Test Matrix Example:** 

| Component          | Test Cases                        | Expected Result      | Severity |
|--------------------|-----------------------------------|----------------------|----------|
| Vehicle Registry   | Create/Edit/Delete vehicle        | Model persists/can retrieve | High |
| Gate API           | Open/Close gate with wrong auth   | 401 Unauthorized     | High |
| MQTT Listener      | Publish valid plate read event    | New vehicle event record, duplicate suppressed | High |
| ANPR Accuracy      | Feed known plate image            | OCR text ~98% correct | Medium |
| Invoice OCR        | Known invoice image               | All fields extracted correctly | High |
| Policy Engine      | Invoice > budget; restricted item | Triggers ALERT       | High |
| Guard Dashboard    | Login & view pending list         | List displays correct entries | Medium |
| Load Test          | 100 vehicles in 1 minute          | No crash; <2s response (k=3 gates) | High |
| Failure Mode       | DB down                          | API returns error code, safe failure | High |
| Privacy/PII        | OCR detects faces or personal data| Should not store/should filter | High |

- **Tools/Commands:** 
  - Run Pytest: `pytest tests/` (assuming tests exist; if not, create them).  
  - Lint/Static: `ruff .`, `mypy .` for type checks.  
  - Migrations: `alembic upgrade head` to test DB setup.  
  - MQTT test: use `mosquitto_pub` CLI to send JSON payload to `frigate/events` topic.  
  - OCR API: `curl -F "file=@test_invoice.jpg" http://localhost:8000/parse_invoice`.  
  - Dashboard: manual or automated UI tests (Selenium) once implemented.

All major changes (ML models, new endpoints) should include a corresponding test. Bug fixes should add regression tests. Priority should be on core functionality: plate ingestion, registry lookup, invoice matching, and human-overrides.

## ROADMAP (Milestones & Timeline)

Below is a phased plan from current state to deployment-ready system, with dependencies and rough effort (person-weeks):

1. **Immediate (1–2 weeks): System Audit & Setup**  
   - Verify current codebase: run existing tests, fix obvious bugs (e.g. missing imports, lint errors). Document any discrepancies between docs and code. (1–2 weeks)  
   - *Output:* Updated `WHAT_HAS_BEEN_DONE.md` with concrete details, initial bug fixes.

2. **Phase 1 (2–4 weeks): Indian ANPR Preparation**  
   - **Data Collection:** Gather a few thousand images from campus gates (with consent). Label plates (bounding boxes + text). (2w)  
   - **Dataset Integration:** Acquire/compile public datasets (DataCluster sample, Kaggle, etc. as much as allowed). Document licenses in `DATASETS_AND_MODELS.md`. (1w)  
   - **Model Training:** Fine-tune a YOLOv9/YOLOv8 model on Indian plates. Fine-tune PaddleOCR on cropped plates (≥5,000 examples per [46]). Evaluate on held-out set. (2–3w, can overlap with data collection)  
   - *Dependencies:* GPU/ML environment setup.  
   - *Deliverable:* Working ANPR model that outperforms Frigate baseline. Updated `DATASETS_AND_MODELS.md`.

3. **Phase 2 (2–3 weeks): Invoice/OCR Pipeline**  
   - **Data Prep:** Collect representative invoices (WhatsApp samples) and augment with Divya52 dataset. Possibly label real ones. (1w)  
   - **OCR & Extraction:** Implement OCR on invoice images (PaddleOCR baseline). Write parsers for key fields. Use regex or small LLM (if feasible) to extract structured data. (1w)  
   - **Verification Logic:** Code the matching rules (order existence, amount check, time). (0.5w)  
   - *Deliverable:* Endpoint that returns {verified/review/reject} for an invoice. Integration test with a few sample images.

4. **Phase 3 (3–4 weeks): Frontend & Guard Workflow**  
   - **Dashboard UI:** Build React app pages (login, live alerts, lists of known/unknown vehicles, pending invoices). Stub data can come from API. (2w)  
   - **Backend Integration:** Expose necessary APIs (e.g. GET /vehicles, POST /alerts/approve). Implement auth (simple JWT). (1.5w)  
   - **Human-in-the-loop Controls:** Add endpoints/buttons for guards to confirm/override events (mark event as ENTRY or EXIT, if accepted or blocked). (0.5w)  
   - *Deliverable:* Usable prototype dashboard. Manual walkthrough test.

5. **Phase 4 (2 weeks): Testing, Reliability, Security**  
   - **Test Suite Expansion:** Add tests identified in BUG_TESTER. Automate in CI. (1w)  
   - **Load Testing & Optimization:** Simulate concurrent events (2–3 gates) to find bottlenecks. Optimize DB indexes, queries. (1w)  
   - **Security Audit:** Code review focusing on SQL injections, auth, secrets management. Implement HTTPS, environment variable secrets for production. (parallel, 1w)  
   - *Deliverable:* All tests passing, performance report, fix critical issues.

6. **Phase 5 (2 weeks): Pilot Deployment**  
   - **Integration:** Deploy to campus environment or a staging server with real cameras.  
   - **Monitoring:** Set up logging (e.g. Sentry) and dashboards (e.g. Grafana) to track uptime, errors. Train guards on using the system. (2w)  
   - *Deliverable:* Pilot evaluation report; fine-tuning of models based on real captures.

7. **Buffer & Iteration (1–2 weeks):**  
   - Address unforeseen bugs, model re-training on new data, user feedback. Security/Compliance checks (if needed).

**Dependencies & Effort:** The AI/ML phases assume availability of one ML engineer (GPUs) and one backend dev (FastAPI, DB), plus a frontend dev. The 12–15 person-weeks estimate covers one full-stack and one ML specialist in parallel. 

**Work Remaining Estimate:** Roughly **60–70%** of total project effort remains.  Code implementation (backend endpoints, UI, rule logic) is ~40% of work; data/model work (collection, labeling, training, evaluation) is ~40%; testing/deployment ~20%. Significant parts of the pipeline still need building, especially ML pipelines and UI.

## Next Steps

1. **Authenticate & Document:** Finalize project documentation (issue tracker, README updates). Create the specified artifacts:  
   - `WHAT_HAS_BEEN_DONE.md`: List completed modules and tests with evidence (file paths, PR references).  
   - `WHAT_HAS_TO_BE_DONE.md`: List outstanding tasks (e.g. “Train and evaluate ANPR model”, “Implement invoice field extraction”).  
   - `BUG_TESTER.md`: Outline test cases as above, with commands/examples.  
   - `DATASETS_AND_MODELS.md`: Catalog datasets/models (links and licensing) and justify choices.  
   - `ROADMAP.md`: Milestones, timelines, dependencies and KPIs (as above).  
   - **Issues/Checklists:** Create GitHub issues for each major task (data collection, model training, UI design, testing, security audit), and sub-tasks with priorities (P1: pipeline reliability, P2: model accuracy, etc.).

2. **POC Implementation:** Begin Phase 1 tasks: collect/annotate plates, fork/clone needed datasets, and start training.  

3. **Regular Reviews:** Hold weekly syncs to demo progress, update this plan, and adjust scope based on findings (e.g. if a pretrained model performs well, we can cut some fine-tuning effort).

The above plan balances urgent system stability (security, bug fixes) with the core research goals (ANPR/OCR). With diligent testing and incremental releases, the CVS-ACS system can move from prototype to a pilot-ready solution by ~3–4 months out, assuming no major roadblocks. 

**Sources:** Project documentation and public sources on ANPR, OCR and datasets. E.g., PaddleOCR fine-tuning guidelines, YOLOv9 improvements, BDD100K vehicle data, existing Indian dataset summaries, and invoice OCR datasets. These inform our strategy for models, data and evaluation.