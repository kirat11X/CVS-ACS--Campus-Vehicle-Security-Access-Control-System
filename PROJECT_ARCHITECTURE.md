# Campus Vehicle Security & Intelligence System
## Research Architecture, System Invariants & Authoritative Topology

> **Document Type:** Research Architecture & Theoretical Foundation Specification  
> **Institution & Deployment Context:** Punjab Engineering College (PEC), Chandigarh  
> **Academic Context:** B.Tech Honors Thesis / Applied Distributed Systems Research  
> **Project Scope:** Distributed Gate Observation Network & Central Authoritative Intelligence Layer  

---

## 1. Executive Summary & Research Context

Perimeter security and vehicle intelligence in a premier academic institution such as **Punjab Engineering College (PEC)** require managing complex, high-volume, and heterogeneous vehicular traffic across multiple geographic entry points:

1. **Heterogeneous Institutional Stakeholders:** The campus serves diverse personas with varying movement contexts—hosteller students, day-scholar students, resident faculty, visiting academics, administrative staff, invited guests, food delivery couriers (Zomato, Swiggy), ride-hailing cabs (Uber, Ola), and unknown/unregistered vehicles.
2. **Distributed Data Acquisition:** Physical perimeters are monitored across distributed observation points (`GATE_1`, `GATE_2`, `GATE_3`), each subjected to asynchronous vehicle passages, varying lighting conditions, and localized sensor noise.
3. **Probabilistic Perception vs. Deterministic Security Intelligence:** Edge sensors (optical cameras, Frigate NVR, RapidOCR/Tesseract engines) operate probabilistically with statistical confidence scores. Security intelligence, historical movement logs, and institutional context must remain deterministic, legally defensible, and fully auditable.

### Critical Operational Grounding: Human-in-the-Loop Security
**This system is NOT an automated gate-opening/closing mechanism.** At PEC, physical barriers and campus gates are operated by authorized human security guards. The software does **NOT** autonomously actuate barriers, control GPIO pins, open barriers, or issue barrier commands.

The software's authoritative mandate is:
$$\mathbf{OBSERVE} \longrightarrow \mathbf{ASSOCIATE} \longrightarrow \mathbf{CONTEXTUALIZE} \longrightarrow \mathbf{RECORD} \longrightarrow \mathbf{ALERT}$$

Security personnel remain the decision-makers and physical operators. The software acts as an authoritative campus intelligence layer that equips guards with immediate institutional context, surfaces verification requirements, and preserves an immutable audit trail.

---

## 2. Authoritative System Topology

```
                   ┌─────────────────────────────────────────────────────────┐
                   │               CENTRAL AUTHORITATIVE SERVER               │
                   │               (Authoritative Campus Brain)              │
                   │                                                         │
                   │  ┌────────────────────────┐  ┌───────────────────────┐  │
                   │  │ VehicleIdentityService │  │  ObservationService   │  │
                   │  └───────────┬────────────┘  └───────────┬───────────┘  │
                   │              │                           │              │
                   │              ▼                           ▼              │
                   │  ┌───────────────────────────────────────────────────┐  │
                   │  │     PostgreSQL 16 Authoritative Campus State      │  │
                   │  │   (Registry, Observations, Context, Audit Logs)   │  │
                   │  └───────────────────────────────────────────────────┘  │
                   └──────────────▲───────────────────────────┬──────────────┘
                                  │ Telemetry Ingestion       │ Context & Alert Stream
                                  │ (MQTT: frigate/#)         │ (Web / Guard Dashboard)
          ┌───────────────────────┼───────────────────────────┼───────────────────────┐
          │                       │                           │                       │
          ▼                       ▼                           ▼                       ▼
   ┌──────────────┐        ┌──────────────┐            ┌──────────────┐        ┌──────────────┐
   │    GATE 1    │        │    GATE 2    │            │    GATE 3    │        │ EXTERNAL /   │
   │ (Main Gate)  │        │(Hostel Gate) │            │ (East Gate)  │        │ CLOUD CHANNELS│
   ├──────────────┤        ├──────────────┤            ├──────────────┤        ├──────────────┤
   │ * Frigate Cam│        │ * Frigate Cam│            │ * Frigate Cam│        │ * WhatsApp   │
   │ * LPR Sensor │        │ * LPR Sensor │            │ * LPR Sensor │        │   Invoices   │
   │ * Local Guard│        │ * Local Guard│            │ * Local Guard│        │ * n8n Webhook│
   │   (Operator) │        │   (Operator) │            │   (Operator) │        │   Automations│
   └──────────────┘        └──────────────┘            └──────────────┘        └──────────────┘
```

### 2.1 The Central Server is Authoritative
* The central server maintains the unified, authoritative state of the campus perimeter:
  * What raw vehicle observations were captured across all gates?
  * Who owns which vehicle, and what is their institutional identity?
  * Is the student a hosteller or day-scholar, and what is their residence context?
  * What is the chronological movement history of a vehicle across campus gates?
  * What security alerts or verification flags require guard intervention?
* All storage, identity resolution, deduplication, and contextual analysis occur exclusively on the central server.

### 2.2 Gate Nodes are Distributed Observation Points
* Gate nodes possess **zero** business logic, **zero** identity resolution responsibility, and **no local decision authority**.
* A gate node:
  1. Captures optical sensor telemetry (video frames, license plate bounding boxes).
  2. Emits an asynchronous, timestamped observation event containing raw sensor observations and confidence metrics.
  3. Displays contextual intelligence and security alerts to the on-duty security guard.

---

## 3. The Ten Core Architectural Invariants

Every subsystem, database model, API endpoint, and background worker must preserve the following ten invariants without exception:

---

### Invariant 1: Gate Nodes are Not Authoritative
> **Formulation:** No gate edge node shall independently maintain campus occupancy state, resolve institutional identities, or make security determinations.

* **Rationale:** Gate nodes are distributed data acquisition points. If edge nodes attempted to maintain localized state or evaluate access privileges, network latency or partitioned links would immediately cause state desynchronization.
* **Implementation:** Gate records (`Gate`) store operational configuration and Frigate camera mappings (`camera_id`). Edge nodes simply publish telemetry to the central broker.

---

### Invariant 2: Central Server is Authoritative
> **Formulation:** Exactly one single source of truth—the central server backed by PostgreSQL—stores raw observations, evaluates identity associations, maintains vehicle movement timelines, and generates security alerts.

* **Rationale:** A multi-gate perimeter requires a single synchronized timeline. Correlating transit duration between gates (e.g. entry at Gate 1 and exit at Gate 3), detecting multi-gate anomalies, and auditing security records require centralized coordination.
* **Implementation:** Domain services (`ObservationService`, `VehicleIdentityService`) execute all business logic within ACID-compliant PostgreSQL transactions.

---

### Invariant 3: Plate ≠ Identity
> **Formulation:** An observed license plate string is merely a sensory token; it is not an identity.

* **Rationale:** A license plate string (e.g., `PB 65 AB 0902`) is an optical label captured by a camera. It can be misread by optical sensors, obscured by mud, mounted on an unregistered vehicle, or transferred between vehicles. Treating the plate as an identity conflates the *sensory token* with the *institutional entity*.
* **Implementation:**
  * Raw sensor strings (`raw_plate`) are preserved alongside standardized versions (`normalized_plate`).
  * `ObservationEvent` records the observation without an `owner_id`.
  * The plate maps to a `Vehicle` record only if registered.
  * Institutional identity is resolved through `Vehicle -> VehicleOwner`.

---

### Invariant 4: Vehicle ≠ Person
> **Formulation:** A physical vehicle is an asset; a person is an institutional legal entity. The relationship between people and vehicles is decoupled.

* **Rationale:**
  * One faculty member may own multiple vehicles (e.g., a car and a two-wheeler).
  * Delivery riders operate commercial fleet vehicles that belong to delivery aggregators or rental companies, not the riders personally.
  * Security notices, disciplinary holds, or department transfers apply to the *person*, not the machinery.
* **Implementation:**
  * Independent database entities: `vehicles` (assets) and `vehicle_owners` (human stakeholders).
  * Foreign key `vehicles.owner_id -> vehicle_owners.id` cleanly supports 1-to-Many ownership, visitor hosting, and delivery fleet profiles.

---

### Invariant 5: Residence Belongs to the Person
> **Formulation:** Residence context (hostel block, room number, off-campus residence address) is an intrinsic property of the human being, never of the machine they operate.

* **Rationale:** A student is a Hosteller residing in "BH-4, Room 312". The student's vehicle does not reside in Room 312; the student does. When a student relocates to another hostel or transitions to a day-scholar, the update is made once on `VehicleOwner` and propagates across all vehicles operated by that student.
* **Implementation:**
  * `person_type` (`STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`) and `residence_type` (`HOSTELLER`, `DAY_SCHOLAR`, `OFF_CAMPUS`, `UNKNOWN`) reside in `VehicleOwner`.
  * `residence` (e.g. `"BH-4, Room 312"`) is stored on `VehicleOwner`.
  * The `vehicles` table contains zero residence columns. `VehicleIdentityService` resolves residence context by traversing to the owner.

---

### Invariant 6: An Observation is Not Automatically an Access Decision
> **Formulation:** The sensory detection of a vehicle constitutes an `ObservationEvent`. It does NOT constitute an `AccessDecision`.

* **Rationale:** An observation records WHAT THE SENSOR SAW (`gate_id`, `camera_id`, `raw_plate`, `plate_confidence`, `vehicle_type`, `direction`). It does not determine authorization or physical access:
  * Physical barrier operation is executed by human security personnel.
  * An observation may have low confidence (e.g. 0.45) or represent an unknown delivery vehicle.
  * Converting an observation into an access decision prematurely eliminates the guard's review discretion and corrupts the observation log with speculative policy outcomes.
* **Implementation:**
  * `ObservationEvent` is completely decoupled from `AccessDecision`.
  * Ingesting an `ObservationEvent` creates **zero** records in `access_decisions`.
  * `ObservationResponse` contains no `decision`, no `threat`, and no `owner`.

#### Phase 6 amendment: direction provenance (declared camera role is configuration, not inference)
> **Formulation:** A movement direction (ENTRY/EXIT) may only come from (a) a camera lane role declared by an administrator (`ENTRY_LANE` / `EXIT_LANE`), (b) a declared zone order on a `BIDIRECTIONAL` lane combined with the order of zones Frigate reports the vehicle entered, or (c) a guard's confirmation. A declared lane role is site configuration entered by a person, not an inference by the system. The system never derives direction from a camera's or gate's name, from which gate a camera belongs to, or from the absence of evidence. Without one of (a)–(c), direction is `UNKNOWN` and no movement is logged.

* The raw `ObservationEvent.direction` keeps what the sensor (or the guard, for MANUAL entries) reported; it is never rewritten.
* The derived direction, its method (`CAMERA_ROLE`, `ZONE_ORDER`, `GUARD_CONFIRMED`) and its evidence (lane role, zone list, confirming user) are stored on the movement record in `entry_exit_logs`.
* A movement record is a fact about passage, not a decision: `decision`, `reason_code` and `decision_id` stay NULL, and no `AccessDecision` is created.

---

### Invariant 7: Every Decision Must be Traceable to Observations + Identity + Policy
> **Formulation:** Any security action, alert, or review recommendation must be fully explainable and linked to the underlying sensory observations, resolved identity, and active campus policies.

* **Rationale:** When security incidents are investigated at PEC (e.g., unauthorized night entry, hit-and-run, theft), security administrators require complete forensic explainability:
  * Which camera recorded the vehicle, and with what LPR confidence score?
  * What raw plate characters were recognized?
  * What institutional identity was linked at that precise timestamp?
  * What rule code (`ReasonCode`) triggered the security notice?
* **Implementation:**
  * Structured audit logging links `EntryExitLog` and `AccessDecision` to `frigate_event_id` and `decision_id`.
  * Structured reason codes provide transparent justification for all system alerts.

---

### Invariant 8: Historical Events Must Never be Destroyed
> **Formulation:** Operational records—observations, gate logs, access evaluations, and vehicle registrations—are append-only. Hard deletion of operational data is prohibited.

* **Rationale:** Physical row deletion (`DELETE FROM ...`) destroys forensic evidence and breaks relational integrity. If a gate is taken offline or a student graduates, historical observations captured at that gate or linked to that vehicle must remain permanently queryable.
* **Implementation:**
  * Safe soft-deactivation pattern:
    * `DELETE /vehicles/{plate}` sets `status = VehicleStatus.INACTIVE`.
    * `DELETE /gates/{gate_id}` sets `status = GateStatus.INACTIVE`.
  * Physical database rows and foreign-key relationships in `observation_events`, `entry_exit_logs`, and `access_decisions` remain permanently intact.
  * Phase 6: movement records in `entry_exit_logs` are append-only (database trigger). A wrong direction or plate is fixed by adding a correction row (`correction_of_id` → original); the effective view uses the latest row and the original stays. Vehicle-to-owner links are append-only `vehicle_link_events`. Presence (inside/outside) is computed on read, never stored as a mutable flag.

---

### Invariant 9: ML Perception and Security Policy Remain Separate
> **Formulation:** Machine learning models (YOLO plate detectors, PaddleOCR/RapidOCR engines) are probabilistic perception tools. They must never contain or enforce access control policies.

* **Rationale:** Computer vision models make statistical predictions with confidence scores. They do not know institutional statutes, curfew hours, or disciplinary holds. Mixing policy into vision scripts creates opaque, non-deterministic security logic that cannot be formally verified.
* **Implementation:**
  * Vision models produce raw sensor outputs: `raw_plate`, `plate_confidence`, `ObservedVehicleType` (`CAR`, `MOTORCYCLE`, `BUS`, `TRUCK`), and `ObservationDirection`.
  * Separate deterministic backend services evaluate security logic and provide context to human operators.

---

### Invariant 10: Three Gates Contribute Observations to One Campus-Wide State
> **Formulation:** Observations from `GATE_1`, `GATE_2`, and `GATE_3` feed a single unified campus observation and movement graph. Gates do not exist in isolation.

* **Rationale:**
  * A vehicle observed entering through Gate 1 and observed at Gate 2 shortly thereafter establishes a cross-campus transit path.
  * Comparing entry and exit timestamps across gates enables transit duration tracking, detection of unauthorized parking in sensitive zones, and multi-gate anomaly detection.
* **Implementation:**
  * Central observation repository queryable across all gates (`GET /observations`, `GET /gates/{id}/observations`, `GET /vehicles/{plate}/observations`).
  * Unified chronological timeline across `GATE_1`, `GATE_2`, and `GATE_3`.

---

## 4. Conceptual System Pipeline

The flow of information through the campus security intelligence architecture progresses through discrete, decoupled stages:

```
[ Vehicle arrives at Gate ]
           │
           ▼
[ Camera Sensor ]
           │
           ▼
[ Frigate NVR (YOLOv9 LPR + PaddleOCR) ]
           │  (Perception: plate, score, vehicle type, event_id)
           ▼
[ Mosquitto MQTT Topic: frigate/events ]
           │
           ▼
[ Central MQTT Ingestion Worker (FrigateMQTTWorker - Phase 4) ]
           │
           ▼
[ FrigateEventParser (Phase 4) ]
           ├─► Camera → Gate resolution (gate_cam -> GATE_1, unknown -> quarantine)
           ├─► Physical vehicle type mapping (car, motorcycle, bus, truck -> ObservedVehicleType)
           ├─► LPR plate extraction & normalization (raw_plate, normalized_plate, score)
           └─► Direction = UNKNOWN (strictly no assumption of entry/exit)
           │
           ▼
[ ObservationService (Phase 3) ]
           ├─► (Phase 6) DirectionResolver: declared lane role / zone order / guard → movement log
           │      UNKNOWN direction → no movement record
           ├─► Plate Normalization (raw: "pb 65 ab 0902" -> norm: "PB65AB0902")
           ├─► Deduplication & Idempotency check via `source_event_id`
           └─► Persistent Storage in `observation_events` table
           │
           ▼  (Future Phase 5)
[ VehicleIdentityService ]
           ├─► Query registered vehicles by normalized_plate
           ├─► Resolve VehicleOwner (PersonType, ResidenceType, Residence)
           └─► Classify: KNOWN, UNKNOWN, or UNRESOLVED (Never auto-label as THREAT)
           │
           ▼
[ Campus Intelligence & Contextualization ]
           ├─► Movement History & Cross-Gate Transit Tracking
           ├─► Curfew / Time-Window Verification
           └─► Delivery Invoice Matching (Zomato/Swiggy via OCR)
           │
           ▼
[ Guard Interface / Security Dashboard ]
           ├─► Real-time vehicle metadata and owner photo/context displayed to guard
           ├─► Verification alerts flagged for guard attention
           │
           ▼
[ Human Security Action ]
           └─► Authorized Security Guard physically verifies and operates gate
```

---

## 5. Physical Vehicle Type vs. Institutional Category

A critical design separation enforced in Phase 3 is the distinction between sensor perception and institutional category:

| Dimension | `ObservedVehicleType` (Sensor Output) | `VehicleCategory` (Institutional Persona) |
| :--- | :--- | :--- |
| **Source** | Computer vision classifier / LPR model | University registration database |
| **Nature** | Physical object geometry | Legal & institutional relationship |
| **Values** | `CAR`, `MOTORCYCLE`, `BUS`, `TRUCK`, `BICYCLE`, `UNKNOWN` | `STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`, `VISITOR`, `DELIVERY`, `RIDE_HAILING`, `UNKNOWN` |
| **Mutability**| Ephemeral to the visual observation | Administrative record tied to owner |
| **Example**| A Zomato delivery rider on a motorcycle: `ObservedVehicleType.MOTORCYCLE` | Registered delivery vehicle: `VehicleCategory.DELIVERY` |

---

## 6. Observation Deduplication & Idempotency

Frigate NVR tracks vehicles across consecutive video frames as they approach the camera, publishing multiple MQTT updates for the same tracked object with increasing optical confidence:

```
Frame 12 (10:31:01): raw_plate="PB65AB1234", plate_confidence=0.71
Frame 28 (10:31:02): raw_plate="PB65AB1234", plate_confidence=0.84
Frame 45 (10:31:03): raw_plate="PB65AB1234", plate_confidence=0.98
```

### Idempotency Guarantee:
* The `source_event_id` (Frigate tracked-object ID) acts as an idempotency key.
* When a sensor update arrives with an existing `(source, source_event_id)` pair:
  * The system **updates/refines** the existing `ObservationEvent` record (updating plate confidence from 0.71 to 0.98 and recording telemetry update counts).
  * It does **NOT** spawn multiple duplicate observation rows in the database.
  * Exactly one physical vehicle passage corresponds to one `ObservationEvent`.

---

## 7. Non-Judgmental Classification: UNKNOWN ≠ THREAT

The observation and intelligence layer strictly avoids premature threat classification:
* An **UNKNOWN** vehicle simply denotes:
  $$\text{"The system could not find an institutional record matching this plate."}$$
* Unknown vehicles are routine occurrences (parents visiting students, delivery couriers with unlinked orders, maintenance contractors, guest lecturers).
* Distinctions maintained by the system:
  * `KNOWN`: Registered campus stakeholder vehicle.
  * `UNKNOWN`: Unregistered vehicle; requires routine guard inquiry.
  * `LOW_CONFIDENCE`: Optical reading below threshold; requires visual plate verification.
  * `THREAT`: Explicit security status assigned only upon human guard confirmation or active blacklist match.

---

## 8. Database Schema & Migration Governance

To maintain schema integrity across all environments, database modifications follow a strict verification protocol:

### 8.1 Candidate Migration Inspection
* Alembic's `--autogenerate` produces candidate migrations that must be reviewed.
* PostgreSQL enum additions (`ALTER TYPE ... ADD VALUE IF NOT EXISTS`) and enum creations require explicit manual statements.

### 8.2 Mandatory Schema Drift Verification (`alembic check`)
* After any model edit, developers and AI agents must run:
  ```bash
  .venv/bin/alembic check
  ```
* **Success Criteria:** Must report:
  ```
  No new upgrade operations detected.
  ```
  with exit code `0`.
* No development phase may conclude while schema drift exists.

---

## 9. Summary Matrix of Invariant Enforcement

| Invariant | Responsible Component | Enforcement Mechanism | Behavior on Violation / Edge Case |
| :--- | :--- | :--- | :--- |
| **1. Gate Non-Authoritative** | `Gate`, `GateResponse` | Gate holds no business logic; only metadata and camera ID | Gates cannot reject or evaluate vehicles locally |
| **2. Central Server Authoritative** | `ObservationService`, PostgreSQL | Centralized ACID transactions across all gate records | Conflicting updates resolved by centralized timeline |
| **3. Plate ≠ Identity** | `ObservationEvent`, `plate_normalizer.py` | `ObservationEvent` stores observed plate strings without `owner_id` | Unregistered plates recorded as observations without owner |
| **4. Vehicle ≠ Person** | `Vehicle`, `VehicleOwner` | 1-to-Many relational decoupling between owners and vehicles | Deactivating an owner revokes authorization across all vehicles |
| **5. Residence Belongs to Person** | `VehicleOwner` table | Residence stored exclusively on `VehicleOwner`, never in `Vehicle` | Residence updates immediately propagate to all owner vehicles |
| **6. Observation ≠ Decision** | `ObservationEvent`, `access_decisions` | `POST /observations` writes to `observation_events`, never `access_decisions` | Ingesting observation creates zero access decisions |
| **7. Decision Traceability** | `EntryExitLog`, `AccessDecision` | Structured audit trail with `ReasonCode` and sensor references | All security notices provide explainable justifications |
| **8. Historical Immutability** | `routes/gates.py`, `routes/vehicles.py` | `DELETE` endpoints execute soft-deactivation (`status=INACTIVE`) | Physical database rows and foreign keys preserved forever |
| **9. Separation of ML & Policy** | `ObservationEvent` vs. Security logic | Probabilistic vision confidence stored as float; no policy inside ML | Low confidence preserves score without auto-rejection |
| **10. Unified Campus State** | Central `ObservationEvent` repository | Observations across all 3 gates queryable through central API | Multi-gate events form a single chronological timeline |
| **6a. Direction Provenance (Phase 6)** | `DirectionResolver`, `camera_lanes`, `entry_exit_logs` | Direction only from declared lane role, declared zone order or guard confirmation; method + evidence stored on the movement | No configuration → `UNKNOWN`, no movement logged; camera names never interpreted |
