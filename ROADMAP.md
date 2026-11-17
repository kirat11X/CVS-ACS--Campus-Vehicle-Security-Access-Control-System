# PRODUCTION ROADMAP & DEPLOYMENT STRATEGY
## Campus Vehicle Security & Access-Control System (CVS-ACS)
### Phased Engineering Milestones, Key Performance Indicators (KPIs), Dependencies, and PEC Pilot Rollout

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Target Deployment Site:** Punjab Engineering College (PEC), Sector 12, Chandigarh (`GATE_1`, `GATE_2`, `GATE_3`)  
**Deployment Strategy:** Phased Rollout (Shadow Mode $\rightarrow$ Guard Assisted $\rightarrow$ Full Campus Security Integration)  
**Guiding Mandate:** Zero autonomous denial of access. Machine learning provides real-time situational awareness; human guards retain 100% operational gate authority.

---

## 1. Master Phased Roadmap Timeline

```
+---------------------------------------------------------------------------------------------------+
|                                     CVS-ACS MASTER ROADMAP SCHEDULE                               |
+-------------------+-----------------------------------+-------------------+-----------------------+
| Milestone         | Stage Name                        | Target Window     | Core Deliverable      |
+-------------------+-----------------------------------+-------------------+-----------------------+
| STAGE 1           | Audit Fix, Hygiene & CI Pipeline  | Days 1–4          | Passing Bug Tester,   |
|                   |                                   |                   | Bipartite Alignment,  |
|                   |                                   |                   | >90% Review Coverage  |
+-------------------+-----------------------------------+-------------------+-----------------------+
| STAGE 2           | Track A OCR & Cloud GPU Training  | Weeks 1–2         | Cloud CCT OCR Training|
|                   |                                   |                   | Qwen3-VL Fine-Tuning, |
|                   |                                   |                   | Real Item Labeling    |
+-------------------+-----------------------------------+-------------------+-----------------------+
| STAGE 3           | Production Backend & Delivery Bus | Weeks 2–4         | Access Control Policy,|
|                   |                                   |                   | WhatsApp Cloud API,   |
|                   |                                   |                   | Security Review Queue |
+-------------------+-----------------------------------+-------------------+-----------------------+
| STAGE 4           | Frontend, Load Testing & Hardening| Weeks 4–5         | React Console Hardening|
|                   |                                   |                   | 100 veh/min Load Test,|
|                   |                                   |                   | TLS Nginx & Sentry    |
+-------------------+-----------------------------------+-------------------+-----------------------+
| STAGE 5           | PEC Campus Pilot & Gate Expansion | Weeks 5–8+        | Gate 1 Shadow Pilot,  |
|                   |                                   |                   | Guard Training,       |
|                   |                                   |                   | Gates 1–3 Deployment  |
+-------------------+-----------------------------------+-------------------+-----------------------+
```

---

## 2. Stage 1: Audit Fix, Code Hygiene & CI Pipeline (Days 1–4)

Stage 1 resolves all lingering code hygiene issues, fixes open review findings from `REVIEW_REPORT.md`, unifies repository documentation, and establishes continuous integration safeguards.

### 2.1 Objectives & Deliverables
- [x] Run `python3 research/cvs_acs_bug_tester.py --repo-root .` and eliminate all warnings and failures.
- [ ] Implement deterministic optimal one-to-one bipartite line-item alignment (Hungarian algorithm) in `research_track/track_b/src/evaluation.py:align_line_items()` (`B-S1-003`).
- [ ] Finalize comma-decimal locale policy (`en-IN`) and handling fee rules in Track B (`B-S2-004`).
- [ ] Expand unit test coverage across `research_track/review/` from **46%** to **$\ge 90\%$**.
- [ ] Clean up local Git root isolation and exclude large (>5 MB) files in `research_track/frontend/node_modules/` (`I-S0-001`, `I-S2-002`).
- [ ] Deploy GitHub Actions CI workflow executing `pytest`, `ruff check`, `mypy`, and `bandit -r backend/`.

### 2.2 Stage 1 Key Performance Indicators (KPIs)
- **Bug Tester Score:** 10 / 10 checks `PASS` in `cvs_acs_bug_tester.py`.
- **Audit Regressions:** 20+ / 20+ scenarios `PASS` in `scripts/test_audit_regressions.py`.
- **Review Coverage:** $\ge 90.0\%$ line coverage across `research_track/review/`.
- **Taxonomy Uniformity:** 100% of documentation files cite the canonical **320 item rows**.

### 2.3 Dependencies & Blockers
- Local workstation running Linux (Fedora 44).
- Python 3.14 `.venv` and Python 3.12 ML virtual environment.

---

## 3. Stage 2: Track A OCR & Real Data Model Training on Cloud GPU (Weeks 1–2)

Stage 2 provisions an AWS EC2 GPU instance to execute the compute-intensive training runs for Track A (License Plate Recognition), Track B (Vision-Language Invoice Parsing), and Track C (Real Campus Item Screening).

```
+-----------------------------------------------------------------------------------------------+
|                                    STAGE 2: CLOUD TRAINING PIPELINE                           |
+-----------------------------------------------------------------------------------------------+
| AWS EC2 g4dn.xlarge (NVIDIA Tesla T4 16 GB VRAM)                                              |
|                                                                                               |
| 1. Track A: CCT OCR (KERAS_BACKEND=torch)                                                     |
|    - Base: cct_s_v2_global.keras (MIT)                                                        |
|    - Dataset: prepared/ocr_in_v1 (13,698 crops) + training_1/ocr_dataset (1,081 crops)        |
|    - Target: CER < 3.0%, Exact Plate Match > 85.0%                                            |
|                                                                                               |
| 2. Track B: Qwen3-VL-2B-Instruct LoRA                                                         |
|    - Base: Qwen/Qwen3-VL-2B-Instruct (4-bit QLoRA)                                            |
|    - Dataset: cord-v2 (2.2 GB) + Divya52 Indian GST (2,000 bills) + 100 Consented Invoices     |
|    - Target: Schema Valid > 98%, Line-Item F1 > 90%                                           |
|                                                                                               |
| 3. Track C: Qwen3-1.7B Real Campus Calibration                                                |
|    - Dataset: 500+ human-labeled real items from campus Zomato/Swiggy/Blinkit receipts        |
|    - Target: Macro-F1 > 0.88, Safe Escalation on Ambiguity (is_uncertain=True -> REVIEW)      |
+-----------------------------------------------------------------------------------------------+
```

### 3.1 Objectives & Deliverables
- [ ] Provision AWS EC2 `g4dn.xlarge` instance using `research_track/hitl_anpr/aws/cloudformation.yaml`.
- [ ] Configure `spot_handler.sh` and `idle_stop.sh` to prevent unexpected spot interruption loss or billing overruns.
- [ ] Train Compact Convolutional Transformer (CCT) OCR with `KERAS_BACKEND=torch` on `prepared/ocr_in_v1` and export to `weights/cct_plate_ocr_best.onnx`.
- [ ] Fine-tune `Qwen3-VL-2B-Instruct` on receipt datasets (`cord-v2`, `invoices-donut-data-v1`, `Divya52 GST`) and real Indian delivery invoices.
- [ ] Collect, curate, and human-label 500+ real delivery line items from PEC students and faculty.
- [ ] Retrain and calibrate `Qwen3-1.7B` QLoRA on the combined synthetic + real item corpus.

### 3.2 Stage 2 Key Performance Indicators (KPIs)
- **Track A Plate OCR:** Exact plate accuracy $\ge 85.0\%$, character error rate (CER) $\le 3.0\%$ on held-out test split.
- **Track B Invoice Parsing:** JSON schema validity $\ge 98.0\%$, arithmetic reconciliation pass rate $\ge 90.0\%$.
- **Track C Policy Screening:** Macro-F1 score $\ge 0.880$, zero false-negative classifications on prohibited contraband (`ALERT`).

### 3.3 Dependencies & Blockers
- AWS IAM credentials with EC2 Spot Instance allocation permissions.
- Access to consented campus delivery invoices from student hostels.

---

## 4. Stage 3: Production Backend Services & Delivery Bus (Weeks 2–4)

Stage 3 finishes the core production backend services, wires the real Meta WhatsApp Business Cloud API, implements the security review queue, and finalizes immutable audit logging.

```
                    +-------------------------------------------------------+
                    |           WhatsApp Business Cloud API (Meta)          |
                    |     Inbound Courier Webhook -> POST /webhooks/whatsapp|
                    +-------------------------------------------------------+
                                                |
                                                v
                    +-------------------------------------------------------+
                    |             DeliveryScreeningService                  |
                    |  Image Sniffing -> PDF Render -> RapidOCR / VLM       |
                    |  Arithmetic Check -> Item Classification              |
                    +-------------------------------------------------------+
                                                |
                                                v
                    +-------------------------------------------------------+
                    |             AccessControlEngine (Phase 5)             |
                    |  Vehicle Registry + Owner Persona + Curfew Rules      |
                    |  Outputs: ALLOW / REVIEW / ALERT + ReasonCode         |
                    +-------------------------------------------------------+
                                                |
                                                v
                    +-------------------------------------------------------+
                    |             Security Review Queue (Phase 11)          |
                    |  GET /security/reviews -> Guard Console Action        |
                    |  POST /security/reviews/{id}/resolve (Append-Only)    |
                    +-------------------------------------------------------+
```

### 4.1 Objectives & Deliverables
- [ ] Implement `AccessControlEngine` (Phase 5) evaluating owner persona rules (Student, Faculty, Visitor, Curfew) and generating immutable `access_decisions` rows.
- [ ] Activate `MetaCloudWhatsAppProvider` with official institutional Meta Graph API credentials (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`) and TLS webhook verification (`hub.verify_token`).
- [ ] Implement `DeliveryVerificationService` connecting courier invoices directly to resident student room context and order clearing workflows.
- [ ] Implement Security Review Queue endpoints (`GET /security/reviews`, `POST /security/reviews/{id}/resolve`) with append-only guard override logging.
- [ ] Enforce camera lane direction confirmation rules: Frigate camera events remain provisional until confirmed by guard or lane sensor.

### 4.2 Stage 3 Key Performance Indicators (KPIs)
- **End-to-End Delivery Latency:** Invoice upload to guard clearance notification $\le 4.5\text{ seconds}$.
- **Access Control Decision Latency:** $p_{95} \le 150\text{ ms}$ for real-time policy evaluation.
- **Audit Immutability:** 100% of guard actions and policy evaluations write append-only records with zero `UPDATE` or `DELETE` operations.

### 4.3 Dependencies & Blockers
- Meta Business Account verification for Punjab Engineering College.
- Staging PostgreSQL instance with applied Alembic migrations.

---

## 5. Stage 4: Frontend, Load Testing, Hardening & Campus Pilot (Weeks 4–5)

Stage 4 connects the remaining security review queues into the React 19 console, performs high-concurrency load testing, configures production TLS proxies, and installs monitoring.

### 5.1 Objectives & Deliverables
- [ ] Integrate Delivery Review Queue, Security Review Queue, and Reason Code badges into `frontend/src/App.tsx`.
- [ ] Add sound and visual alert notifications (`Web Audio API` + `Capacitor Local Notifications`) for high-priority security alerts.
- [ ] Execute Locust / JMeter stress testing simulating **100 vehicles/minute** across PEC Gates 1, 2, and 3.
- [ ] Deploy Nginx reverse proxy with TLS 1.3, rate-limiting (60 req/min public, 300 req/min staff), and CORS headers.
- [ ] Integrate Sentry application error tracking and Prometheus/Grafana metrics dashboards.
- [ ] Implement automated PostgreSQL backup script and 30-day snapshot data retention policy.

### 5.2 Stage 4 Key Performance Indicators (KPIs)
- **Peak Load Throughput:** 100 vehicles/minute with $p_{95} \le 450\text{ ms}$ and 0 unhandled errors.
- **Security SAST Quality:** Zero critical or high findings in `bandit -r backend/` and zero TypeScript build errors.
- **Observability:** 100% of service errors captured in Sentry with stack traces and request IDs.

---

## 6. Stage 5: PEC Campus Pilot & Multi-Gate Rollout (Weeks 5–8+)

The physical campus deployment follows an incremental three-gate rollout strategy to validate real-world conditions without disrupting daily campus traffic.

```
+---------------------------------------------------------------------------------------------------+
|                                      PEC CAMPUS ROLLOUT ROADMAP                                   |
+-------------------+-------------------------------+-----------------------------------------------+
| Phase             | Location                      | Operating Mode & Scope                        |
+-------------------+-------------------------------+-----------------------------------------------+
| Phase 5A (Week 5) | PEC Gate 1 (Main Sector 12)   | Shadow Mode Pilot (Telemetry & AI Logging;    |
|                   |                               | Guards operate physical gates as normal;      |
|                   |                               | Compare AI suggestions vs guard manual logs)  |
+-------------------+-------------------------------+-----------------------------------------------+
| Phase 5B (Week 6) | PEC Gate 1 (Main Sector 12)   | Active Guard-Assisted Mode (Guards use console|
|                   |                               | for 1-click clearance, visitor passes, alerts)|
+-------------------+-------------------------------+-----------------------------------------------+
| Phase 5C (Week 7) | PEC Gate 2 (Hostel Gate)      | Hostel Delivery Intake & 2-Wheeler Monitoring;|
|                   |                               | Student curfew tracking & Zomato clearing     |
+-------------------+-------------------------------+-----------------------------------------------+
| Phase 5D (Week 8+)| PEC Gate 3 (Staff Gate) +     | Full Campus Perimeter Operations;             |
|                   | Unified 3-Gate Tracking       | Cross-gate transit timing & global presence   |
+-------------------+-------------------------------+-----------------------------------------------+
```

### 6.1 Gate 1 Shadow Mode Pilot Protocol (Week 5)
1. **Parallel Operation:** Cameras at Gate 1 feed telemetry into Frigate and CVS-ACS. The software records observations, identifies plates, and logs proposed `ALLOW`/`REVIEW`/`ALERT` verdicts.
2. **Zero Guard Disruption:** Guards continue logging vehicles using their standard paper/register protocol.
3. **Daily Discrepancy Auditing:** Security supervisors compare automated CVS-ACS logs against physical guard logs:
   - Identify plate recognition false positives and misreads.
   - Fine-tune camera angles, lighting compensation, and confidence thresholds.
   - Verify that 0 authorized campus members would have been wrongly turned away.

### 6.2 Guard Training & Operational Handover (Week 6)
- Provide physical training sessions for PEC security staff across all shifts (Morning, Evening, Night).
- Train guards on:
  - 1-click confirmation of recognized vehicles on the mobile console.
  - Quick manual license plate lookup and override entry.
  - Delivery verification review (clearing food couriers in $<10\text{ seconds}$).
  - Handling security alerts (blacklisted plates, curfew violations).

---

## 7. Risk Management & Contingency Matrix

```
+------------------------------------+----------+--------+----------------------------------------------+
| Risk Description                   | Severity | Impact | Mitigation Strategy                          |
+------------------------------------+----------+--------+----------------------------------------------+
| 1. High-beam headlight glare at    | HIGH     | Medium | Install polarizing lens filters on gate      |
|    night blinds plate cameras      |          |        | cameras; tune Frigate WDR & exposure timing. |
+------------------------------------+----------+--------+----------------------------------------------+
| 2. Motorcycle rear plates bent,    | MEDIUM   | Medium | Retrain YOLO11n on small-dimension crops;    |
|    mud-covered, or unreadable      |          |        | guard console prompts for quick manual entry.|
+------------------------------------+----------+--------+----------------------------------------------+
| 3. Campus WiFi drops at Gate 2/3   | HIGH     | High   | Deploy local Ethernet backhaul; React PWA    |
|    disconnecting guard mobile app  |          |        | caches local state with automatic reconnect. |
+------------------------------------+----------+--------+----------------------------------------------+
| 4. Meta WhatsApp Business API      | MEDIUM   | Low    | Fall back to local LAN mobile intake page    |
|    approval delayed by institutional|          |        | (http://<server-ip>:8000/intake); zero delay.|
|    verification                    |          |        |                                              |
+------------------------------------+----------+--------+----------------------------------------------+
| 5. Guard fatigue or resistance to  | MEDIUM   | High   | Design ultra-simple UI (large buttons, high  |
|    using tablet/phone interface    |          |        | contrast, minimal typing, audible chimes).   |
+------------------------------------+----------+--------+----------------------------------------------+
```

---

## 8. Definition of Done (Final Project Acceptance)

The CVS-ACS project is formally completed and accepted when:
1. All three PEC perimeter gates (`GATE_1`, `GATE_2`, `GATE_3`) actively stream video telemetry into the central server with zero dropped frames.
2. Plate recognition accuracy exceeds **90%** on daytime traffic and **80%** on night traffic across statutory Indian license plates.
3. Food and parcel delivery invoices are screened and verified within **5 seconds** via WhatsApp or the mobile intake portal.
4. The React 19 web/mobile console is deployed on guard devices across all shifts with 100% uptime over a 14-day continuous evaluation period.
5. All 10 Core Research Invariants are mathematically and operationally preserved with an immutable, append-only forensic audit trail.
