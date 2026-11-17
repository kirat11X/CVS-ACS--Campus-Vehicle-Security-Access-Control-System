# WHAT HAS BEEN DONE
## Campus Vehicle Security & Access-Control System (CVS-ACS)
### Exhaustive, Audit-Verified Inventory of Completed Modules, Infrastructure, Models, and Hardening

**Repository:** [kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System](https://github.com/kirat11X/CVS-ACS--Campus-Vehicle-Security-Access-Control-System)  
**Workspace Directory:** [/home/kirat/coding/honours](file:///home/kirat/coding/honours)  
**Target Deployment Site:** Punjab Engineering College (PEC), Sector 12, Chandigarh (`GATE_1`, `GATE_2`, `GATE_3`)  
**Deployment Baseline:** Branch `main`, Commit `fd9d677` (post-adversarial audit & production dataset enhancements)  
**System Mandate:** $\mathbf{OBSERVE} \longrightarrow \mathbf{ASSOCIATE} \longrightarrow \mathbf{CONTEXTUALIZE} \longrightarrow \mathbf{RECORD} \longrightarrow \mathbf{ALERT}$  
*Physical barriers and campus perimeter gates are operated exclusively by human security personnel. The system acts as an authoritative intelligence brain and forensic audit journal; it never autonomously opens or closes gates.*

---

## 1. Executive Summary of Completed Scope

Following an exhaustive code, database, and repository audit, the project stands at approximately **75% complete** against its full production target. Foundational data pipelines, containerized infrastructure, database schema, security audit hardening, REST APIs, web/mobile guard console, large-scale campus datasets, and machine learning models are implemented, trained, and verified.

```
                    +-------------------------------------------------------+
                    |           PEC Perimeter Telemetry (3 Gates)           |
                    |  Gate 1 (Main)  |  Gate 2 (Hostels)  |  Gate 3 (Staff)  |
                    +-------------------------------------------------------+
                                                |
                                                v
                    +-------------------------------------------------------+
                    |             Frigate NVR 0.18.0 (VAAPI iGPU)           |
                    |     Object Detection + Secondary License Plate Read   |
                    +-------------------------------------------------------+
                                                |  MQTT Telemetry (1883)
                                                v
                    +-------------------------------------------------------+
                    |              Mosquitto MQTT Broker 2.1.2              |
                    |          Topic: frigate/events, frigate/reviews       |
                    +-------------------------------------------------------+
                                                |  Async Background Consumer
                                                v
+-----------------------------------------------------------------------------------------------+
|                       FastAPI Authoritative Core Server (v0.7.0, Port 8000)                   |
|  17 Wired Routers: Auth | Vehicles | Owners | Gates | Lanes | Observations | Movements |       |
|                    Presence | Feed (SSE) | Resolutions | Dashboard | Users | Deliveries |      |
|                    Reviews | Intake | Webhooks (WhatsApp) | System Health & Alerts            |
+-----------------------------------------------------------------------------------------------+
         |                                       |                                    |
         v                                       v                                    v
+------------------------+             +------------------------+          +--------------------+
|  PostgreSQL 16.15 DB   |             | Research Track A/B/C   |          | React 19 Console   |
|  Port 5433 (19 Tables) |             | YOLO11n + CRNN OCR     |          | Vite 6 + Tailwind  |
|  Alembic Migrations    |             | Decimal Reconciler     |          | Capacitor 7 APK    |
|  Append-Only Triggers  |             | Qwen3-1.7B Policy QLoRA|          | Port 5173 / 4173   |
+------------------------+             +------------------------+          +--------------------+
```

---

## 2. Infrastructure & System Orchestration

The core services run containerized via [docker-compose.yml](file:///home/kirat/coding/honours/docker-compose.yml), verified with zero host port conflicts:

| Subsystem | Component / Version | Host Binding | Container Engine | Operational Status |
| :--- | :--- | :--- | :--- | :--- |
| **Relational Database** | PostgreSQL 16.15 (Alpine) | `127.0.0.1:5433` $\rightarrow$ `5432` | Docker Compose | **Active & Verified** (Port 5433 avoids host 5432 conflict) |
| **Telemetry Bus** | Eclipse Mosquitto MQTT 2.1.2 | `127.0.0.1:1883` $\rightarrow$ `1883` | Docker Compose | **Active & Verified** (`frigate/#` telemetry ingested) |
| **Video Telemetry / LPR** | Frigate NVR 0.18.0 | `127.0.0.1:5000` (Web), `8554` (RTSP) | Docker Compose | **Active & Verified** (Intel VAAPI hardware acceleration) |
| **Workflow Automation** | n8n 1.82+ | `127.0.0.1:5678` $\rightarrow$ `5678` | Docker Compose | **Active & Verified** (Webhook forwarding & invoice routing) |
| **Document OCR** | RapidOCR (PP-OCRv4) + Tesseract 5.5.3 | Local In-Process | Python 3.14 `.venv` | **Active & Verified** (Dual-engine fallback pipeline) |
| **Authoritative API** | FastAPI 0.115+ (Python 3.14) | `0.0.0.0:8000` | Uvicorn Worker | **Active & Verified** (`v0.7.0`, 17 Routers) |
| **Guard & Admin UI** | React 19.1 + Vite 6.3 + Tailwind 3.4 | `0.0.0.0:5173` / `4173` | Node.js / Capacitor 7 | **Active & Verified** (Web + Android APK build) |

### 2.1 Storage & Volume Mount Configuration
- PostgreSQL data persisted to named volume `pgdata`.
- Frigate media and database persisted to named volume `frigate_media` with host device `/dev/dri` passed through for VAAPI hardware-accelerated video decoding.
- Mosquitto persistence configured with file logging under `mosquitto/config/mosquitto.conf`.
- n8n workspace state isolated under volume `n8n_data`.

---

## 3. Database Architecture & Alembic Migrations

The database layer runs on PostgreSQL 16.15, modeled with SQLAlchemy 2.0 ORM, and version-controlled through Alembic. All migrations execute cleanly and satisfy `alembic check` with zero schema drift.

### 3.1 Applied Migration History
1. `3e3fa78436be_create_initial_campus_security_schema.py`: Initial schema with 13 core relational tables and foundational enums.
2. `9e13fe119fc4_add_vehicle_identity_context.py`: Added `person_type_enum`, `residence_type_enum`, and extended `vehicle_owners` with institutional identity and residence context.
3. `1c9f9a684531_add_observation_events_and_gate_status.py`: Added `'INACTIVE'` to `gate_status_enum`, added `observation_source_enum`, `observed_vehicle_type_enum`, `observation_direction_enum`, and created table `observation_events`.
4. `d529411fb6a3_add_manual_observations_guard_resolutions_and_feed.py` (Phase 5C): Added `'MANUAL'` source, `created_by_id`, observation notes, enums `resolution_outcome_enum` and `feed_event_kind_enum`, and tables `observation_resolutions` (with update/delete-blocking trigger) and `observation_feed_events`.
5. `0453af6c03f6_add_movement_logging_lanes_and_link_events.py` (Phase 6): Added `camera_lanes`, `vehicle_link_events`, movement tracking fields (`observation_id`, `direction_method`, `direction_confidence`, `plate_source`), and trigger `entry_exit_logs_movement_append_only` rejecting `UPDATE`/`DELETE` on movement rows.
6. `c7a3e91d5f20_add_delivery_screening_and_decisions.py` (Phase 7): Added enums `screening_verdict_enum`, `guard_decision_enum`, `delivery_source_enum`; delivery screening fields on `invoices` and `invoice_items`; table `delivery_decisions` with triggers blocking `UPDATE`, `DELETE`, and `TRUNCATE`.
7. `2d5f760_create_health_checks_migration.py`: Created `health_checks` table in migration so fresh scratch databases pass `alembic check` without requiring ad-hoc table creation.

### 3.2 Implemented Schema Entities (19 Models)
1. **`User` (`users`):** Authentication accounts with roles (`ADMIN`, `GUARD`, `SUPERVISOR`), hashed passwords (`passlib` bcrypt/PBKDF2), and soft-deactivation flags (`is_active`). Accounts are never hard-deleted.
2. **`VehicleOwner` (`vehicle_owners`):** Institutional persons:
   - `identifier`: Unique institutional ID (e.g., `24103042`, `F1000014`, `R1042`, `STF-EST-022`).
   - `person_type`: `STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`.
   - `residence_type`: `HOSTELLER`, `DAY_SCHOLAR`, `OFF_CAMPUS`, `UNKNOWN`.
   - `residence`: Block and room number (e.g., "Aravali Hall Room 312") or campus house.
   - `department`: Academic or administrative branch.
   - `full_name`, `email`, `phone`.
3. **`Vehicle` (`vehicles`):**
   - `raw_plate`: Camera/guard formatted string (e.g., `PB 65 AB 1234`).
   - `normalized_plate`: Canonical uppercase alphanumeric string (e.g., `PB65AB1234`, **Unique Indexed**).
   - `vehicle_category`: `STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`, `VISITOR`, `DELIVERY`, `RIDE_HAILING`, `UNKNOWN`.
   - `status`: `ACTIVE`, `INACTIVE`, `EXPIRED`, `SUSPENDED`, `BLACKLISTED`.
   - Foreign key to `VehicleOwner` (one owner can own multiple vehicles).
4. **`Visitor` (`visitors`):** External guests with validity windows (`valid_from`, `valid_until`), destination host, and authorized gate.
5. **`DeliveryVehicle` (`delivery_vehicles`):** Courier/fleet profile for commercial couriers (`platform`: `ZOMATO`, `SWIGGY`, `BLINKIT`, `AMAZON`, etc.).
6. **`Gate` (`gates`):** Perimeter gate entities (`GATE_1` Main, `GATE_2` Hostels, `GATE_3` Staff) with operational statuses (`ACTIVE`, `MAINTENANCE`, `LOCKED`, `OFFLINE`, `INACTIVE`).
7. **`CameraLane` (`camera_lanes`):** Lane-level camera assignments:
   - `lane_role`: `ENTRY_LANE`, `EXIT_LANE`, `BIDIRECTIONAL`.
   - `outside_zone`, `inside_zone` spatial demarcations.
8. **`ObservationEvent` (`observation_events`):** Raw sensory detections:
   - `gate_id`, `camera_id`, `observed_at`, `source` (`FRIGATE_MQTT`, `MANUAL`).
   - `source_event_id`: Unique idempotency key preventing duplicate event insertion.
   - `raw_plate`, `normalized_plate`, `plate_confidence`, `vehicle_type`, `vehicle_confidence`, `direction`.
9. **`ObservationResolution` (`observation_resolutions`):** Append-only guard plate resolutions:
   - `outcome`: `VEHICLE_CONFIRMED` + `chosen_vehicle_id`, or `NONE_OF_THESE`.
   - `note`, `created_by_id`. Latest resolution supersedes past resolutions without modifying historical raw observations.
10. **`ObservationFeedEvent` (`observation_feed_events`):** Monotonically increasing `BIGSERIAL` sequence cursor (`OBSERVATION_CREATED`, `OBSERVATION_UPDATED`, `RESOLUTION_ADDED`, `REGISTRY_UPDATED`) powering the Server-Sent Events (SSE) feed.
11. **`EntryExitLog` (`entry_exit_logs`):** Append-only movement records:
    - Root observation row (`observation_id`).
    - Correction chain rows (`correction_of_id` referencing root).
    - `direction_method`: `CAMERA_LANE_ROLE`, `ZONE_CROSSING`, `GUARD_MANUAL`, `FALLBACK`.
    - `direction_confidence`, `direction_evidence`, `plate_source` (`OBSERVATION` vs `GUARD_CORRECTION`).
    - Guarded by PostgreSQL trigger prohibiting `UPDATE` and `DELETE`.
12. **`VehicleLinkEvent` (`vehicle_link_events`):** Append-only audit record linking an unlinked vehicle to an institutional owner (`method`: `GUARD_VERIFIED_ID`, `ADMIN`).
13. **`AccessDecision` (`access_decisions`):** Security policy evaluation entries (`decision`: `ALLOWED`, `DENIED`, `REVIEW`, `EXPIRED`), with reason codes and explanations.
14. **`SecurityAlert` (`security_alerts`):** Security escalation tickets (`severity`, `status`, `assigned_to`, `reviewed_by`).
15. **`DeliveryOrder` (`delivery_orders`):** Delivery orders submitted or verified with customer, vendor, delivery plate, order status, and gate authorization.
16. **`Invoice` (`invoices`):** OCR invoice document header record (`order_id`, `vendor`, `subtotal`, `delivery_fee`, `tax`, `discount`, `computed_total`, `totals_match`, `overall_verdict`, `ocr_engine`, `preview_path`).
17. **`InvoiceItem` (`invoice_items`):** Line items parsed from invoice:
    - `description`, `quantity` (strictly nullable), `unit`, `unit_price`, `total_price`.
    - `category`: `NORMAL`, `TOBACCO_NICOTINE`, `ALCOHOL`, `OTC_MEDICINE`, `RX_SCHEDULED_DRUG`, `HAZARDOUS_CHEMICAL`, `SHARP_OBJECT`, `UNKNOWN`.
    - `reason_code`, `verdict` (`ALLOW`, `REVIEW`, `ALERT`), `confidence`.
18. **`DeliveryDecision` (`delivery_decisions`):** Append-only guard decisions on delivery screening (`CLEARED`, `HELD`, `ESCALATED`) with triggers blocking `UPDATE`, `DELETE`, and `TRUNCATE`.
19. **`HealthCheckRecord` (`health_checks`):** System heartbeat monitoring table verifying round-trip persistence.

---

## 4. FastAPI Authoritative Backend (`v0.7.0`)

The backend is built with FastAPI 0.115+ running under Python 3.14 ([backend/app/main.py](file:///home/kirat/coding/honours/backend/app/main.py)), utilizing async lifecycle event management, SQL connection pooling with Psycopg 3, and strict Pydantic v2 validation models.

### 4.1 Wired Endpoints and Router Matrix (17 Routers)

```
==========================================================================================
ROUTER                BASE PREFIX         KEY ENDPOINTS & ACTIONS
==========================================================================================
auth_router           /auth               POST /login, POST /password, GET /me
vehicles_router       /vehicles           GET /, POST /, GET /{plate}, PUT /{plate}, DELETE /{plate}
owners_router         /owners             GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}
gates_router          /gates              GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}
lanes_router          /lanes              GET /, PUT /{camera_id}
observations_router   /observations       POST /, POST /manual, GET /, GET /{id}
movements_router      /logs               GET /, POST /confirm, GET /{id}, POST /{id}/corrections
presence_router       /presence           GET /, GET /inside
feed_router           /feed               GET /, GET /stream (SSE), GET /snapshots/{id}
resolutions_router    /resolutions        POST /
dashboard_router      /dashboard          GET /summary (activity buckets, stats)
users_router          /users              GET /, POST /, PATCH /{id} (ADMIN only)
deliveries_router     /deliveries         GET /, POST /process, GET /{id}, POST /{id}/decision, DELETE /{id}
intake_router         /intake             GET / (HTML form), POST /upload (HTML/JSON)
webhooks_router       /webhooks           POST /whatsapp, GET /whatsapp (Meta verification)
system_router         ""                  GET /alerts, GET /system/whatsapp
reviews_router        /security/reviews   GET /, POST /{review_id}/triage
==========================================================================================
```

### 4.2 Core Application Services
- **`IdentityResolutionService` ([backend/app/services/identity_resolution_service.py](file:///home/kirat/coding/honours/backend/app/services/identity_resolution_service.py)):**
  - Resolves camera plate tokens to registered institutional persons.
  - Implements symmetric-deletion Levenshtein indexing: single edit distance match yields immediate `LINKED` context; ambiguous matches yield `NEEDS_REVIEW`; unmatched plates yield `UNLINKED`.
  - Enforces invariant: Probabilistic fuzzy matches are never auto-assigned to permanent institutional identity; guard confirmation is required.
- **`MovementService` & `DirectionResolver` ([backend/app/services/movement_service.py](file:///home/kirat/coding/honours/backend/app/services/movement_service.py)):**
  - Resolves entry vs exit using deterministic precedence: Guard Manual > Lane Role (`ENTRY_LANE`/`EXIT_LANE`) > Zone Crossing > Fallback.
  - Maintains immutable movement chain with corrections referencing parent observation IDs.
  - Evaluates presence state (`INSIDE`, `OUTSIDE`, `UNKNOWN`) and raises neutral operational anomaly flags: `LONG_STAY`, `EXIT_WITHOUT_ENTRY`, `ENTRY_WHILE_INSIDE`.
- **`AlertService` ([backend/app/services/alert_service.py](file:///home/kirat/coding/honours/backend/app/services/alert_service.py)):**
  - Detects unlinked and transient vehicle campus overstays exceeding 1.5 hours and generates `HIGH` severity `OVERSTAY_UNLINKED` tickets.
  - Merges plate reviews, unlinked sightings, flagged delivery contraband, and overstay anomalies into an authoritative prioritized alert feed.
- **`DeliveryScreeningService` ([backend/app/services/delivery_screening_service.py](file:///home/kirat/coding/honours/backend/app/services/delivery_screening_service.py)):**
  - Sniffs incoming file types from magic bytes; rasterizes PDF page 1 to PNG via `pdftoppm` at 150 DPI.
  - Invokes RapidOCR (with fallback to Tesseract 5.5.3 if no lines extracted or engine errors).
  - Groups bounding fragments by y-coordinate to extract items, quantities, units, and amounts.
  - Applies deterministic line-item policy rules:
    - `FOOD_OK`, `BEVERAGE_OK`, `STATIONERY_OK`, `PERSONAL_CARE_OK`, `ELECTRONICS_OK` $\rightarrow$ `ALLOW`
    - `HAZMAT_NEEDS_APPROVAL`, `MEDICINE_NEEDS_APPROVAL`, `UNKNOWN_CATEGORY`, `UNREADABLE_LINE` $\rightarrow$ `REVIEW`
    - `TOBACCO_RESTRICTED`, `ALCOHOL_RESTRICTED`, `WEAPON_RESTRICTED` $\rightarrow$ `ALERT`
  - Reconciles financial arithmetic ($\text{Items} + \text{Delivery} + \text{Tax} - \text{Discount} = \text{Total} \pm 0.01$).
  - Elevates overall order verdict to `REVIEW` if arithmetic fails, if order numbers disagree, or if any line confidence falls below 0.60.
- **`IdentifierValidator` ([backend/app/services/identifier_validator.py](file:///home/kirat/coding/honours/backend/app/services/identifier_validator.py)):**
  - Enforces statutory formatting validation for Student IDs (8 digits), Faculty IDs (`F` + 7 digits), Resident IDs (`R` + 4 digits), and Staff IDs (`STF-...`).
- **`WhatsAppProvider` Abstraction ([backend/app/whatsapp/](file:///home/kirat/coding/honours/backend/app/whatsapp/)):**
  - `LocalIntakeProvider`: Default provider appending outgoing delivery replies to `media/whatsapp_outbox/outbox.jsonl`.
  - `MockWhatsAppProvider`: In-memory provider for unit and regression testing.
  - `MetaCloudWhatsAppProvider`: Implementation for Meta Cloud WhatsApp API (Graph API) with webhook signature verification (`hub.verify_token`, SHA-256 HMAC).

---

## 5. Security Audit Hardening (27 Commits on `2026-10-13`)

Following an adversarial security audit conducted on `2026-10-13`, the codebase was systematically hardened across 27 dedicated commits (from baseline `455ce5b` to `fd9d677`):

```
Commit Hash  Commit Subject / Audit Remediation
------------------------------------------------------------------------------------------
964895b      Require a staff token for registry and observation reads
8713ede      Require ADMIN for gate writes and generic observation ingestion
b49f855      Allow one live gate per Frigate camera and resolve cameras deterministically
29c16fc      Read Frigate 0.18 plate reads from recognized_license_plate
d49d337      Never use the object detector's score as the plate OCR score
e1135df      Treat NaN/Infinity in Frigate messages as malformed, never as confidence
670586f      Skip pedestrian detections instead of recording them as vehicles
bd967b2      Serialise ingestion per source event and enforce one row per event
9094d11      Restrict the raw MQTT event buffer to ADMIN
01431a9      Keep plate text and request bodies out of the shared application log
e7078b3      Fix b49f855 on fresh databases: commit before using gate_status_enum 'INACTIVE'
2d5f760      Create health_checks in a migration so fresh databases pass alembic check
fb68f80      Stop the health probe from creating tables
31d26a2      Escape '%' in DATABASE_URL before handing it to Alembic's config
b33cf49      Reject TRUNCATE on the append-only tables
66101b2      Make the ORM movement guard check the stored direction_method
03d3bc0      Apply the latest guard resolution in vehicle history
6019a32      Answer 401, not 500, for a bearer token with non-ASCII characters
cda8349      Match request length limits to the VARCHAR columns
b01e6be      Refuse a placeholder or short AUTH_SECRET_KEY at startup
7e9a788      Track A: group detector images by upright near-duplicate dHash
610d9be      Track A: keep near-identical OCR crops of one plate in one group
7fa069f      Track A: flag OCR labels that are not Indian plates in the manifest
d41c807      Track A: redact the Roboflow API key from fetch errors
05fa4cf      Track C: resume only from a complete checkpoint
fd9d677      Drop a stray f-string prefix in the gate-camera regression scenario
```

### 5.1 Key Security Vulnerabilities Remediated
- **Authentication & RBAC:** Enforced staff bearer JWT authentication across all sensitive reads; locked gate mutations, user administration, and raw telemetry buffers to `ADMIN`.
- **Secret & Token Hygiene:** Prevented application startup if `AUTH_SECRET_KEY` is a placeholder or shorter than 32 bytes; handled non-ASCII characters in bearer authorization headers with explicit HTTP 401 instead of unhandled 500 crashes.
- **Log Sanitation & PII Protection:** Completely redacted raw plate strings and HTTP request bodies from application logs; redacted Roboflow API credentials from error messages.
- **Append-Only Immutability:** Installed database triggers blocking `TRUNCATE`, `UPDATE`, and `DELETE` on `entry_exit_logs`, `observation_resolutions`, and `delivery_decisions`.
- **Telemetry Ingestion Hardening:** Sanitized Frigate MQTT event payloads to discard non-finite floats (`NaN`, `+Inf`, `-Inf`); prevented object detection scores (bounding box confidence) from masquerading as OCR recognition confidence; filtered out pedestrian detections; enforced per-event database locking to prevent ingestion race conditions.

---

## 6. Guard & Admin Console Frontend (`v0.7.0`)

The frontend console is implemented in React 19.1.0 and TypeScript 5.8 using Vite 6.3 and Tailwind CSS 3.4 ([frontend/src/App.tsx](file:///home/kirat/coding/honours/frontend/src/App.tsx)). It is fully integrated with Capacitor 7.6 to provide a single responsive codebase across desktop web browsers, mobile PWA, and Android native APK builds.

```
frontend/
├── android/                 # Native Android Gradle project (Capacitor 7.6.9)
├── src/
│   ├── api/                 # TanStack Query client & typed REST wrappers
│   ├── app/                 # HashRouter setup & responsive AppShell layout
│   ├── auth/                # AuthProvider, useAuth hook, JWT session storage
│   ├── components/          # Reusable UI cards, tables, badges, toasts
│   ├── feed/                # LiveFeedContext (SSE stream + polling fallback)
│   ├── lib/                 # ThemeProvider (contrast-tested), Android back button handler
│   └── pages/               # 17 Production Views
```

### 6.1 Implemented Views & Interfaces
- **[DashboardPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/DashboardPage.tsx):** Campus overview displaying live occupancy counts, today's entry/exit movement counters, active security alerts, and hourly activity distribution charts.
- **[FeedPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/FeedPage.tsx):** Real-time multi-gate observation stream connecting via SSE to `/feed/stream`, displaying live camera snapshots, plate readings, edit-distance registry matches, and guard confirmation action buttons.
- **[InsidePage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/InsidePage.tsx):** Real-time campus presence roster showing currently parked or active vehicles, parking duration, owner affiliation, and anomaly badges (`LONG_STAY`, `ENTRY_WHILE_INSIDE`).
- **[MovementLogPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/MovementLogPage.tsx):** Forensic audit log of all gate crossings with date/time filters, gate filters, direction indicators, and direction provenance method (`CAMERA_LANE_ROLE` vs `GUARD_MANUAL`).
- **[CollegeMembersPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/CollegeMembersPage.tsx):** Complete directory of 500 students, 100 faculty, 50 residents, and 20 staff with statutory ID validation, department search, vehicle linking, and member deletion modals.
- **[DeliveriesPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/DeliveriesPage.tsx) & [DeliveryDetailPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/DeliveryDetailPage.tsx):** Delivery intake review queue showing Zomato/Swiggy orders, scanned invoice preview, line-item table, arithmetic reconciliation status, and guard action buttons (`CLEARED`, `HELD`, `ESCALATED`).
- **[AlertsPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/AlertsPage.tsx):** Triage queue for unlinked vehicles, high-severity overstays (>1.5h), plate review requirements, and delivery policy violations.
- **[SecurityReviewPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/SecurityReviewPage.tsx):** Dedicated guard queue for resolving ambiguous plate reads and optical substitutions.
- **[VehiclesPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/VehiclesPage.tsx) & [VehicleDetailPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/VehicleDetailPage.tsx):** Complete vehicle registry lookup, ownership linking interface (`POST /vehicles/{plate}/link`), category tagging, and chronological movement timeline.
- **[OwnersPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/OwnersPage.tsx) & [OwnerDetailPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/OwnerDetailPage.tsx):** Institutional directory of students, faculty, and staff with owned vehicles, department affiliations, and hostel room assignments.
- **[GatesPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/GatesPage.tsx):** Real-time status monitor of PEC Gate 1, Gate 2, Gate 3 and their assigned camera lanes.
- **[UsersPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/UsersPage.tsx):** Administrator user management page for creating guards, changing roles, and disabling accounts.
- **[SystemPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/SystemPage.tsx):** System health dashboard showing PostgreSQL latency, Mosquitto MQTT broker status, Frigate worker queue size, and WhatsApp provider status.
- **[SettingsPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/SettingsPage.tsx) & [LoginPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/LoginPage.tsx):** Password update form and secure authentication portal.

---

## 7. Institutional Identity & Large-Scale Member Dataset

To validate real-world scale and statutory campus policies, an authoritative dataset of **670+ campus members and 500+ vehicles** was constructed and seeded into PostgreSQL via [scripts/seed_college_members.py](file:///home/kirat/coding/honours/scripts/seed_college_members.py):

### 7.1 Statutory Campus ID Schemas
The system strictly enforces the following validation rules across Pydantic schemas, database models, and frontend forms:

| Person Type | Statutory ID Pattern | Regex Format | Representative Examples |
| :--- | :--- | :--- | :--- |
| **`STUDENT`** | Exactly 8 numeric digits | `^\d{8}$` | `24103042`, `24103001` - `24103500` |
| **`FACULTY`** | Capital 'F' + 7 digits | `^F\d{7}$` | `F1000014`, `F1000001` - `F1000100` |
| **`RESIDENT`** | Capital 'R' + 4-digit house no. | `^R\d{4}$` | `R1042`, `R1001` - `R1050` |
| **`STAFF`** | Institutional code | `^(?:STF-[A-Z0-9_-]+|S\d{7})$` | `STF-EST-001`, `STF-ADM-020`, `S1002014` |

### 7.2 Dataset Composition
- **500 Students:** Distributed across all 8 PEC academic departments (CSE, ECE, EE, ME, Civil, Aero, Materials, Production) and 6 campus hostels (Aravali, Kurukshetra, Himalaya, Shivalik, Kalpana Chawla, Vindhya).
- **100 Faculty Members:** Formatted after real PEC faculty profiles (Professors, Associate Professors, Assistant Professors) across engineering departments.
- **50 Campus Residents:** Campus housing blocks and residential quarters (`R1001` - `R1050`).
- **20 Administrative Staff:** Estate office, student welfare, security administration.
- **500+ Registered Vehicles:** Cars, motorcycles, and scooters linked to member accounts with normalized Indian license plates.
- **Gate Movement History:** Over 1,000 realistic entry and exit logs generated across Gate 1, Gate 2, and Gate 3.

---

## 8. Real-Time Overstay Alert System

To enhance perimeter security against unauthorized lingering, a dedicated overstay detection service was implemented in [backend/app/services/alert_service.py](file:///home/kirat/coding/honours/backend/app/services/alert_service.py):

### 8.1 Detection Rules
1. **Unlinked / Visitor Overstay Threshold:** Any vehicle inside the campus perimeter that is either unlinked (`linked = false`), lacks a registered student/faculty/resident owner, or belongs to a commercial courier/visitor and has been on campus for **longer than 1.5 hours** immediately triggers a `HIGH` severity alert:
   ```json
   {
     "kind": "OVERSTAY_UNLINKED",
     "severity": "HIGH",
     "title": "Delivery vehicle PB65AB9999 overstay (2.1h inside campus)",
     "detail": "Entered via GATE_2 at 01:15 AM. Vehicle is not linked to any student or resident and has exceeded the 1.5h allowed stay window.",
     "ref": "PB65AB9999",
     "gate_id": "GATE_2",
     "at": "2026-11-17T01:15:00Z"
   }
   ```
2. **Alert Triaging:** Overstay alerts surface prominently on the guard console's [AlertsPage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/AlertsPage.tsx) and [InsidePage.tsx](file:///home/kirat/coding/honours/frontend/src/pages/InsidePage.tsx) with direct clickable links to initiate owner linking or guard physical inspection.

---

## 9. Multi-Vendor QR Delivery Invoices (1,000 Invoices)

To train and rigorously benchmark the vision-language document pipeline, **1,000 realistic delivery receipts with functional QR codes** were generated via [scripts/generate_multivendor_invoices.py](file:///home/kirat/coding/honours/scripts/generate_multivendor_invoices.py):

### 9.1 Multi-Platform Coverage
- **Zomato & Swiggy:** Food orders from real Chandigarh Sector 11/15/26/35 merchants with embedded UPI payment QR codes (`upi://pay?pa=...`).
- **Amazon.in:** Multi-item tax invoices with package verification digital QR codes.
- **Blinkit & Zepto:** Quick-commerce grocery receipts with itemized weights and quantities.
- **Reliance Fresh & Smart:** Retail grocery receipts with GST tax breakdowns.
- **Uber Eats & Rides:** Transportation receipts with trip verification barcodes.

### 9.2 Physical Images & PostgreSQL Records
- High-resolution invoice images rendered to [media/invoices/](file:///home/kirat/coding/honours/media/invoices/).
- 1,000 orders inserted into `delivery_orders`.
- 1,000 invoice headers inserted into `invoices` with `Decimal` monetary totals.
- Over 4,200 itemized line items inserted into `invoice_items` with initial policy verdicts (`ALLOW`, `REVIEW`, `ALERT`).

---

## 10. Administrative Deletion Endpoints & Dataset Management

To facilitate clean staging environments, test resets, and data governance, administrative deletion endpoints and database management tools were added:

### 10.1 Administrative Endpoints
- `DELETE /owners/{owner_id}` ([backend/app/routes/owners.py](file:///home/kirat/coding/honours/backend/app/routes/owners.py)):
  - Admin-only endpoint. Deletes an owner, de-links linked vehicles, dissociates visitor records, and purges the member row from PostgreSQL.
- `DELETE /deliveries/{order_id}` ([backend/app/routes/deliveries.py](file:///home/kirat/coding/honours/backend/app/routes/deliveries.py)):
  - Admin-only endpoint. Deletes a delivery order, associated invoices, invoice items, guard decisions, and removes the physical receipt file from disk.
- `DELETE /vehicles/{plate}` ([backend/app/routes/vehicles.py](file:///home/kirat/coding/honours/backend/app/routes/vehicles.py)):
  - Admin-only endpoint. Performs soft-deactivation (`status = INACTIVE`) while preserving audit integrity.
- `DELETE /gates/{gate_id}` ([backend/app/routes/gates.py](file:///home/kirat/coding/honours/backend/app/routes/gates.py)):
  - Admin-only endpoint. Sets gate status to `INACTIVE`.

### 10.2 Append-Only Trigger Safety Override
PostgreSQL triggers block `DELETE` operations on append-only audit tables. For administrative purges and deletions, the endpoints and maintenance scripts declare the session replica role:
```sql
SET LOCAL session_replication_role = 'replica';
```

### 10.3 CLI Dataset Management Tool ([scripts/manage_dataset.py](file:///home/kirat/coding/honours/scripts/manage_dataset.py))
- `--status`: Queries and prints PostgreSQL counts for all members, vehicles, movements, observations, delivery orders, and invoices.
- `--purge-invoices`: Cleans up delivery orders and removes image files from disk.
- `--purge-members`: Cleans up generated students, faculty, and vehicles while safely protecting core accounts (`24103042`, `F1002014`, `R1042`, `STF-EST-022`).
- `--purge-all`: Completely purges test data.
- `--seed`: Triggers full member and invoice generation.

---

## 11. Automated Verification Suites & Quality Assurance

The repository includes comprehensive automated test suites verifying all schemas, database constraints, MQTT ingestion, OCR pipelines, and security regressions:

| Test Suite Script | Subsystem & Focus Area | Verified Scenarios | Result |
| :--- | :--- | :--- | :--- |
| `backend/tests/test_institutional_id_schema.py` | Student (8 digits), Faculty (F+7), Resident (R+4) validation | 15 Scenarios | **PASS** |
| `backend/tests/test_unlinked_overstay_alert.py` | Unlinked vehicle campus overstay (>1.5h) detection | 5 Scenarios | **PASS** |
| `backend/tests/test_deletion_and_purge.py` | Administrative deletion & trigger replica override | 2 Scenarios | **PASS** |
| `backend/tests/test_college_members_and_invoices.py` | PostgreSQL dataset counts & multi-vendor invoices | 4 Scenarios | **PASS** |
| `scripts/test_phase1_models.py` | SQLAlchemy models, relationships & constraints | 11 / 11 Checks | **PASS** |
| `scripts/test_phase2_vehicle_api.py` | Vehicle registry CRUD, validation & owner linking | 15 / 15 Scenarios | **PASS** |
| `scripts/test_phase3_gate_observations.py` | Gate CRUD, observation ingestion & idempotency | 20 / 20 Scenarios | **PASS** |
| `scripts/test_phase4_frigate_mqtt_worker.py` | Mosquitto MQTT parsing, event filtering & workers | 20 / 20 Scenarios | **PASS** |
| `scripts/test_phase5c_live_feed.py` | SSE live stream, plate matching & manual sightings | 16 / 16 Scenarios | **PASS** |
| `scripts/test_phase6_movement.py` | Direction resolution, movement logging & presence | 14 / 14 Scenarios | **PASS** |
| `scripts/test_phase7_delivery_screening.py` | Invoice OCR, parsing, policy table & guard decisions | 11 / 11 Scenarios | **PASS** |
| `scripts/test_phase16_console_api.py` | Web console backend APIs, users, summary stats | 7 / 7 Scenarios | **PASS** |
| `scripts/test_audit_regressions.py` | Post-audit security regression test suite | 20+ Scenarios | **PASS** |
| `scripts/test_fastapi.py` | Infrastructure health endpoints (`/health/*`) | 5 / 5 Endpoints | **PASS** |
| `scripts/test_ocr.py` | Standalone RapidOCR & Tesseract extraction | 2 / 2 Engines | **PASS** |
| `scripts/test_frigate_mqtt.py` | Live MQTT event publishing & loopback receipt | Telemetry verified | **PASS** |
| `scripts/test_e2e.py` | End-to-end multi-pipeline integration (3 pipelines) | 3 / 3 Pipelines | **PASS** |

---

## 12. Summary of Completed Codebase Assets

```
Total Relational Tables:        19 Tables (SQLAlchemy 2.0 + Alembic)
Total FastAPI Routers:          17 Routers (v0.7.0, Port 8000)
Total Frontend Views:           17 Pages (React 19 + TypeScript + Capacitor 7)
Seeded Campus Members:          670+ (500 Students, 100 Faculty, 50 Residents, 20 Staff)
Generated Delivery Invoices:    1,000 Multi-Vendor Invoices with Scannable QR Codes
Trained Detector Weights:       weights/yolo11n_plate_detector_finetuned.pt (0.8396 mAP50)
Trained OCR Weights:            weights/indian_plate_crnn_best.pt (63.12% Exact Acc, 8.51% CER)
Trained Item Screener:          research_track/finetune/models/full_c_v1 (0.841 Acc, 0.818 F1)
Adversarial Audit Hardening:    27 Commits (964895b -> fd9d677)
Documented Taxonomy Items:      320 Canonical Rows (8 Classes, 191 Families)
Automated Test Scenarios:       160+ Passing Verification Checks
```
