# CVS-ACS REST API Specification & Reference
## Campus Vehicle Security & Access Control System
### Version: 0.7.0 | Protocol: HTTP/1.1 & Server-Sent Events (SSE) | Format: JSON / Multipart

**Base URL:** `http://localhost:8000` (or `http://<server-ip>:8000`)  
**Interactive Swagger UI:** `http://localhost:8000/docs`  
**Interactive Redoc:** `http://localhost:8000/redoc`  
**OpenAPI Specification:** `http://localhost:8000/openapi.json`  

---

## 1. Authentication & Role-Based Access Control (RBAC)

All endpoints—except public health probes, the public LAN courier intake portal, and Meta WhatsApp verification webhooks—require a JSON Web Token (JWT) passed in the `Authorization` header.

```http
Authorization: Bearer <access_token>
```

### 1.1 User Roles & Privilege Matrix
The system enforces strict hierarchical RBAC:

| Role Code | Description | Permitted Capabilities |
| :--- | :--- | :--- |
| **`ADMIN`** | Campus Chief Security Officer & System Administrators | Full read/write access. User management, gate creation, camera lane updates, direct observation ingestion, soft-deactivations, and administrative record deletion. |
| **`GUARD`** / **`STAFF`** | Security personnel at Gate 1, 2, 3 and desk supervisors | Read all operational rosters, registries, and logs. Submit manual observations, confirm plate resolutions, record movement corrections, link vehicles, and triage delivery clearances. |
| **`PUBLIC`** | Courier riders & automated external webhooks | Restricted access to public endpoints: `/intake` portal, `/webhooks/whatsapp`, and `/health`. |

---

## 2. API Endpoint Catalog

```
========================================================================================================
PREFIX / TAG          METHOD   PATH                                     AUTH        SUMMARY
========================================================================================================
/auth                 POST     /auth/login                              Public      Exchange credentials for JWT bearer token
/auth                 GET      /auth/me                                 Staff       Retrieve current authenticated user profile
/auth                 POST     /auth/password                           Staff       Update current user password
--------------------------------------------------------------------------------------------------------
/vehicles             GET      /vehicles                                Staff       Search and list registered vehicles
/vehicles             POST     /vehicles                                Staff       Register new campus vehicle
/vehicles             GET      /vehicles/{plate}                        Staff       Get vehicle profile by normalized plate
/vehicles             PUT      /vehicles/{plate}                        Staff       Update vehicle category, status, or owner
/vehicles             DELETE   /vehicles/{plate}                        Admin       Soft-deactivate vehicle (status = INACTIVE)
/vehicles             GET      /vehicles/{plate}/observations           Staff       List all sensory sightings for plate
/vehicles             POST     /vehicles/{plate}/link                   Staff       Link unlinked vehicle to campus member
/vehicles             GET      /vehicles/{plate}/history                Staff       Chronological crossing audit timeline
--------------------------------------------------------------------------------------------------------
/owners               GET      /owners                                  Staff       Query institutional member directory
/owners               POST     /owners                                  Admin       Create student, faculty, resident, staff
/owners               GET      /owners/{owner_id}                       Staff       Retrieve member profile & owned vehicles
/owners               PUT      /owners/{owner_id}                       Admin       Update member contact, room, or role
/owners               DELETE   /owners/{owner_id}                       Admin       Permanently delete member from PostgreSQL
--------------------------------------------------------------------------------------------------------
/gates                GET      /gates                                   Staff       List all perimeter gates and status
/gates                POST     /gates                                   Admin       Register new perimeter gate
/gates                GET      /gates/{gate_id}                         Staff       Get gate details & assigned cameras
/gates                PUT      /gates/{gate_id}                         Admin       Update gate name or operational status
/gates                DELETE   /gates/{gate_id}                         Admin       Soft-deactivate gate (status = INACTIVE)
/gates                GET      /gates/{gate_id}/observations            Staff       Recent observation events at gate
--------------------------------------------------------------------------------------------------------
/lanes                GET      /lanes                                   Staff       List all camera lanes & zone mappings
/lanes                PUT      /lanes/{camera_id}                       Admin       Configure camera gate, lane role & zones
--------------------------------------------------------------------------------------------------------
/observations         GET      /observations                            Staff       List recent raw camera observations
/observations         POST     /observations                            Admin       Ingest raw MQTT sensory detection event
/observations         POST     /observations/manual                     Staff       Record manual guard sighting at gate
/observations         GET      /observations/{id}                       Staff       Retrieve single observation event
--------------------------------------------------------------------------------------------------------
/logs (Movements)     GET      /logs                                    Staff       Query effective vehicle movement log
/logs (Movements)     POST     /logs/confirm                            Staff       Guard confirms Entry/Exit direction
/logs (Movements)     GET      /logs/{log_id}                           Staff       Retrieve detailed movement entry
/logs (Movements)     POST     /logs/{log_id}/corrections               Staff       Append guard direction correction
--------------------------------------------------------------------------------------------------------
/presence             GET      /presence                                Staff       Campus presence summary at point-in-time
/presence             GET      /presence/inside                         Staff       Live roster of vehicles currently inside
--------------------------------------------------------------------------------------------------------
/feed                 GET      /feed                                    Staff       Paginated event cursor history
/feed                 GET      /feed/stream                             Staff       Real-time Server-Sent Events (SSE) feed
/feed                 GET      /feed/snapshots/{observation_id}         Staff       Download raw camera snapshot image
--------------------------------------------------------------------------------------------------------
/resolutions          POST     /resolutions                             Staff       Confirm plate match (append-only)
--------------------------------------------------------------------------------------------------------
/dashboard            GET      /dashboard/summary                       Staff       24-hour activity metrics & counts
--------------------------------------------------------------------------------------------------------
/security/reviews     GET      /security/reviews                        Staff       List pending triage review items
/security/reviews     POST     /security/reviews/{review_id}/triage     Staff       Submit guard triage decision
--------------------------------------------------------------------------------------------------------
/deliveries           GET      /deliveries                              Staff       List delivery orders & screening status
/deliveries           POST     /deliveries/process                      Staff       Process and screen delivery invoice
/deliveries           GET      /deliveries/{order_id}                   Staff       Get delivery order & line item manifest
/deliveries           GET      /deliveries/{order_id}/invoice-image     Staff       Download processed invoice image
/deliveries           POST     /deliveries/{order_id}/decision          Staff       Append guard decision (CLEARED/HELD)
/deliveries           DELETE   /deliveries/{order_id}                   Admin       Delete delivery order & associated items
--------------------------------------------------------------------------------------------------------
/intake               GET      /intake                                  Public      Public LAN courier intake upload HTML
/intake               POST     /intake/upload                           Public      Submit courier invoice file & details
--------------------------------------------------------------------------------------------------------
/webhooks             GET      /webhooks/whatsapp                       Public      Meta Cloud WhatsApp webhook verification
/webhooks             POST     /webhooks/whatsapp                       Public      Receive inbound WhatsApp message webhook
--------------------------------------------------------------------------------------------------------
Root & System         GET      /alerts                                  Staff       Unified security needs-attention alerts
                      GET      /system/whatsapp                         Staff       Check active messaging provider status
                      GET      /health                                  Public      Fast container liveness check
                      GET      /health/db                               Public      PostgreSQL connection & latency check
                      GET      /health/mqtt                             Public      Mosquitto broker connection check
                      GET      /health/all                              Public      Comprehensive infrastructure health check
                      GET      /api/workers/frigate-worker              Staff       Frigate MQTT worker processing statistics
                      POST     /webhook/n8n-test                        Public      Automated pipeline test verification hook
========================================================================================================
```

---

## 3. Detailed Endpoint Documentation

### 3.1 Authentication Subsystem (`/auth`)

#### `POST /auth/login`
- **Description:** Authenticates staff credentials and issues an HMAC-SHA256 bearer token.
- **Access Level:** Public
- **Request Body:**
  ```json
  {
    "username": "guard_gate1",
    "password": "Password123!"
  }
  ```
- **Responses:**
  - `200 OK`:
    ```json
    {
      "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
      "token_type": "bearer",
      "expires_at": "2026-11-17T18:00:00Z",
      "user": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "username": "guard_gate1",
        "full_name": "Sgt. Balwinder Singh",
        "role": "GUARD"
      }
    }
    ```
  - `401 Unauthorized`: Invalid username or password.

#### `GET /auth/me`
- **Description:** Returns the profile of the authenticated user.
- **Access Level:** Staff (`GUARD`, `ADMIN`, `SUPERVISOR`)
- **Responses:**
  - `200 OK`: `UserSummary` object.
  - `401 Unauthorized`: Token missing, expired, or invalid.

#### `POST /auth/password`
- **Description:** Updates the password for the current user session.
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "current_password": "OldPassword123!",
    "new_password": "NewStrongPassword456!"
  }
  ```
- **Responses:**
  - `204 No Content`: Password changed successfully.
  - `400 Bad Request`: Current password incorrect or new password does not meet complexity rules.

---

### 3.2 Vehicle Management Subsystem (`/vehicles`)

#### `GET /vehicles`
- **Description:** Search and retrieve registered vehicles.
- **Access Level:** Staff
- **Query Parameters:**
  - `q` (string, optional): Search plate substring, make, or owner name.
  - `category` (string, optional): Filter by `STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`, `VISITOR`, `DELIVERY`, `RIDE_HAILING`.
  - `status` (string, optional): Filter by `ACTIVE`, `INACTIVE`, `SUSPENDED`, `BLACKLISTED`.
  - `skip` (integer, default: `0`): Pagination offset.
  - `limit` (integer, default: `50`, max: `200`): Page size.
- **Responses:**
  - `200 OK`: Array of `VehicleDetailResponse` objects.

#### `POST /vehicles`
- **Description:** Registers a new vehicle in the campus registry.
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "plate": "PB65AB1234",
    "category": "STUDENT",
    "make_model": "Hyundai i20 (White)",
    "color": "White",
    "owner_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
  ```
- **Responses:**
  - `201 Created`: `VehicleDetailResponse` with normalized plate (`PB65AB1234`).
  - `409 Conflict`: Vehicle with normalized plate already registered.

#### `GET /vehicles/{plate}`
- **Description:** Retrieve vehicle profile, owner context, and current presence status by plate number. Accepts raw or normalized formats.
- **Access Level:** Staff
- **Responses:**
  - `200 OK`: `VehicleDetailResponse`.
  - `404 Not Found`: Plate not found in registry.

#### `DELETE /vehicles/{plate}`
- **Description:** Soft-deactivates vehicle registration (`status = INACTIVE`). Historical crossing logs and observations are preserved intact.
- **Access Level:** Admin Only
- **Responses:**
  - `200 OK`:
    ```json
    {
      "status": "success",
      "message": "Vehicle 'PB65AB1234' soft-deactivated successfully.",
      "vehicle_status": "INACTIVE"
    }
    ```
  - `404 Not Found`: Plate not found.

#### `POST /vehicles/{plate}/link`
- **Description:** Links an unlinked vehicle to an institutional member with verification provenance.
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "owner_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "verification_method": "GUARD_VERIFIED_ID",
    "notes": "Verified physical PEC student ID card at Gate 1."
  }
  ```
- **Responses:**
  - `201 Created`: `VehicleLinkResponse` confirming ownership link event.

---

### 3.3 Institutional Member Subsystem (`/owners`)

#### `GET /owners`
- **Description:** Queries the campus institutional directory (students, faculty, residents, staff).
- **Access Level:** Staff
- **Query Parameters:**
  - `q` (string, optional): Search member name, institutional identifier, or phone.
  - `person_type` (string, optional): `STUDENT`, `FACULTY`, `STAFF`, `RESIDENT`.
  - `department` (string, optional): Academic or administrative branch.
  - `skip` (integer, default: `0`): Pagination offset.
  - `limit` (integer, default: `50`, max: `200`): Page size.
- **Responses:**
  - `200 OK`: Array of `OwnerContextResponse` objects.

#### `POST /owners`
- **Description:** Creates an institutional member record. Enforces statutory identifier schema.
- **Access Level:** Admin Only
- **Request Body:**
  ```json
  {
    "identifier": "24103042",
    "full_name": "Kirat Singh",
    "email": "kiratsingh.be24@pec.edu.in",
    "phone": "+91 98765 43210",
    "person_type": "STUDENT",
    "residence_type": "HOSTELLER",
    "residence": "Aravali Hall, Room 312",
    "department": "Computer Science & Engineering"
  }
  ```
  *Statutory Schema Rules:*
  - `STUDENT`: Exactly 8 numeric digits (`24103001` - `24103999`).
  - `FACULTY`: Capital 'F' + 7 digits (`F1000001` - `F1999999`).
  - `RESIDENT`: Capital 'R' + 4-digit house number (`R1001` - `R9999`).
  - `STAFF`: Institutional code (`STF-EST-022`, `S1234567`).
- **Responses:**
  - `201 Created`: `OwnerContextResponse`.
  - `400 Bad Request`: Identifier format validation failed.
  - `409 Conflict`: Identifier or email already registered.

#### `DELETE /owners/{owner_id}`
- **Description:** Deletes an institutional owner from PostgreSQL. Safely de-links associated vehicles and dissociates visitor records without violating foreign keys.
- **Access Level:** Admin Only
- **Responses:**
  - `200 OK`:
    ```json
    {
      "status": "success",
      "message": "Owner 'Kirat Singh' (24103042) deleted successfully from PostgreSQL.",
      "deleted_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    }
    ```
  - `404 Not Found`: Owner ID not found.

---

### 3.4 Perimeter Gate & Camera Lane Subsystem (`/gates`, `/lanes`)

#### `GET /gates`
- **Description:** List all perimeter gates with operational statuses and active camera assignments.
- **Access Level:** Staff
- **Responses:**
  - `200 OK`: Array of `GateResponse` (`GATE_1`, `GATE_2`, `GATE_3`).

#### `PUT /gates/{gate_id}`
- **Description:** Update gate operational status (`ACTIVE`, `MAINTENANCE`, `LOCKED`, `OFFLINE`, `INACTIVE`).
- **Access Level:** Admin Only
- **Request Body:**
  ```json
  {
    "name": "Gate 1 (Main Sector 12)",
    "status": "MAINTENANCE",
    "notes": "North entry lane barrier hydraulic repair."
  }
  ```
- **Responses:**
  - `200 OK`: Updated `GateResponse`.

#### `PUT /lanes/{camera_id}`
- **Description:** Configure camera-to-gate mapping and directional role.
- **Access Level:** Admin Only
- **Request Body:**
  ```json
  {
    "gate_id": "GATE_1",
    "lane_role": "ENTRY_LANE",
    "outside_zone": "sector12_road",
    "inside_zone": "campus_boulevard",
    "description": "Gate 1 Lane 1 North Inbound Camera"
  }
  ```
- **Responses:**
  - `200 OK`: `LaneResponse`.

---

### 3.5 Observations & Real-Time Feed Subsystem (`/observations`, `/feed`, `/resolutions`)

#### `POST /observations/manual`
- **Description:** Records an ad-hoc manual observation when a camera is obstructed or vehicle has damaged plates.
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "gate_id": "GATE_1",
    "raw_plate": "PB 65 AB 1234",
    "observed_at": "2026-11-17T03:30:00Z",
    "note": "Front plate missing, read from rear bumper plate.",
    "chosen_vehicle_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
  ```
- **Responses:**
  - `201 Created`: `ResolvedObservation` with immediate movement generation.

#### `GET /feed/stream`
- **Description:** Server-Sent Events (SSE) telemetry stream providing live observation cards and guard resolution events to connected consoles.
- **Access Level:** Staff (via Bearer header or `?token=` query param for EventSource compatibility)
- **Response Format:** `text/event-stream; charset=utf-8`
- **Event Structure:**
  ```
  event: OBSERVATION_CREATED
  id: 1042
  data: {"observation_id":"...","plate":"PB65AB1234","confidence":0.96,"gate_id":"GATE_1","direction":"ENTRY"}
  ```

#### `POST /resolutions`
- **Description:** Appends a guard resolution confirming or rejecting a candidate plate match.
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "observation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "outcome": "VEHICLE_CONFIRMED",
    "chosen_vehicle_id": "7ca23f11-9217-4861-a1fc-1c883f55bba2",
    "note": "Verified driver is registered resident Dr. Bansal."
  }
  ```
- **Responses:**
  - `201 Created`: `ResolutionCreated` confirming resolution persistence.

---

### 3.6 Movement Logs & Campus Presence (`/logs`, `/presence`)

#### `GET /logs`
- **Description:** Queries the forensic movement journal. Reflects the effective state with latest guard corrections applied.
- **Access Level:** Staff
- **Query Parameters:**
  - `plate` (string, optional): Filter by exact or partial plate.
  - `gate_id` (string, optional): `GATE_1`, `GATE_2`, `GATE_3`.
  - `direction` (string, optional): `ENTRY` or `EXIT`.
  - `date_from` (ISO datetime, optional): Start window.
  - `date_to` (ISO datetime, optional): End window.
  - `linked` (boolean, optional): `true` for registered campus vehicles, `false` for unlinked.
  - `skip` (integer, default: `0`): Offset.
  - `limit` (integer, default: `50`, max: `200`): Limit.
- **Responses:**
  - `200 OK`: `MovementPage` with items and total count.

#### `POST /logs/{log_id}/corrections`
- **Description:** Appends a correction row pointing to an earlier movement entry. Historical rows are never modified.
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "corrected_direction": "EXIT",
    "note": "Vehicle reversed out through Gate 2."
  }
  ```
- **Responses:**
  - `201 Created`: `MovementDetail` with correction chain link.

#### `GET /presence/inside`
- **Description:** Live roster of all vehicles currently positioned inside the campus perimeter.
- **Access Level:** Staff
- **Query Parameters:**
  - `q` (string, optional): Search by plate or owner name.
  - `as_of` (ISO datetime, optional): Point-in-time calculation.
- **Responses:**
  - `200 OK`:
    ```json
    {
      "total": 42,
      "items": [
        {
          "subject": "PB65AB1234",
          "status": "INSIDE",
          "normalized_plate": "PB65AB1234",
          "linked": true,
          "inside_since": "2026-11-17T01:15:00Z",
          "owner": {
            "name": "Kirat Singh",
            "institutional_id": "24103042",
            "person_type": "STUDENT"
          }
        }
      ]
    }
    ```

---

### 3.7 Delivery Screening & Invoices (`/deliveries`, `/intake`)

#### `GET /deliveries`
- **Description:** Lists delivery orders and their automated screening audit verdicts.
- **Access Level:** Staff
- **Query Parameters:**
  - `status` (string, optional): `PENDING_REVIEW`, `VERIFIED`, `COMPLETED`, `CANCELLED`.
  - `screening_verdict` (string, optional): `ALLOW`, `REVIEW`, `ALERT`.
- **Responses:**
  - `200 OK`: Array of `DeliverySummary` records.

#### `POST /deliveries/process`
- **Description:** Uploads a delivery receipt image or PDF for automated dual-engine OCR and policy classification.
- **Access Level:** Staff
- **Multipart Form Parameters:**
  - `file`: Scanned receipt image (PNG, JPEG) or digital PDF invoice.
  - `order_id`: Commercial order reference (e.g. `ZOM-20261117-0042`).
  - `platform`: `ZOMATO`, `SWIGGY`, `BLINKIT`, `ZEPTO`, `AMAZON`, `UBER`, `RELIANCE`.
  - `customer_name`: Name of resident/student recipient.
  - `delivery_vehicle_plate`: Courier vehicle license plate.
- **Responses:**
  - `201 Created`: `DeliveryDetail` containing categorized line items, computed totals, arithmetic match flag, and overall verdict.

#### `POST /deliveries/{order_id}/decision`
- **Description:** Appends the guard's physical screening decision (`CLEARED`, `HELD`, `ESCALATED`).
- **Access Level:** Staff
- **Request Body:**
  ```json
  {
    "decision": "CLEARED",
    "note": "Package contents physically verified; matches meal invoice."
  }
  ```
- **Responses:**
  - `201 Created`: `DeliveryDetail` with updated decision chain.

#### `DELETE /deliveries/{order_id}`
- **Description:** Deletes a delivery order, its associated invoices, line items, decisions, and on-disk image preview (ADMIN only).
- **Access Level:** Admin Only
- **Responses:**
  - `200 OK`:
    ```json
    {
      "status": "success",
      "message": "Delivery order 'ZOM-20261117-0042' and all associated invoices/items deleted successfully from PostgreSQL.",
      "deleted_order_id": "ZOM-20261117-0042"
    }
    ```
  - `404 Not Found`: Order ID not found.

---

### 3.8 Security Alerts & System Health (`/alerts`, `/health`)

#### `GET /alerts`
- **Description:** Aggregates everything requiring guard attention, ordered by severity (`HIGH` $\rightarrow$ `MEDIUM` $\rightarrow$ `LOW`).
- **Access Level:** Staff
- **Query Parameters:**
  - `limit` (integer, default: `50`, max: `200`)
- **Responses:**
  - `200 OK`: Array of `AlertItem` objects:
    ```json
    [
      {
        "kind": "OVERSTAY_UNLINKED",
        "severity": "HIGH",
        "title": "Delivery vehicle PB65AB9999 overstay (2.1h inside campus)",
        "detail": "Entered via GATE_2 at 01:15 AM. Vehicle is not linked to any student or resident and has exceeded the 1.5h allowed stay window.",
        "ref": "PB65AB9999",
        "gate_id": "GATE_2",
        "at": "2026-11-17T01:15:00Z"
      }
    ]
    ```

#### `GET /health/all`
- **Description:** Comprehensive health diagnostic checking PostgreSQL latency, Mosquitto MQTT broker connection, Frigate worker queue size, and WhatsApp provider availability.
- **Access Level:** Public / Monitoring Probes
- **Responses:**
  - `200 OK`:
    ```json
    {
      "status": "ok",
      "database": {"status": "ok", "latency_ms": 1.42},
      "mqtt": {"status": "ok", "broker": "localhost:1883"},
      "frigate_worker": {"running": true, "events_processed": 1420},
      "whatsapp": {"provider": "local", "available": true}
    }
    ```
  - `503 Service Unavailable`: Core component (DB or MQTT) unhealthy.

---

## 4. HTTP Status Code Conventions

| Status Code | Meaning | Circumstance |
| :--- | :--- | :--- |
| `200 OK` | Request Succeeded | Read queries, soft-deactivations, and administrative deletions. |
| `201 Created` | Resource Created | Entity creation, manual sightings, append-only logs, and resolutions. |
| `204 No Content` | No Content | Successful password modification. |
| `400 Bad Request` | Validation Failure | Invalid statutory identifier, malformed JSON, or missing required fields. |
| `401 Unauthorized` | Auth Required | Missing, expired, malformed, or non-ASCII bearer token. |
| `403 Forbidden` | Privilege Insufficient | Non-admin user attempting gate creation, owner deletion, or user management. |
| `404 Not Found` | Entity Missing | Unknown vehicle plate, owner ID, gate ID, or delivery order. |
| `409 Conflict` | Unique Key Collision | Duplicate normalized plate, username, or source event ID. |
| `422 Unprocessable` | Schema Mismatch | Pydantic v2 payload type or constraint error. |
| `503 Service Unavailable` | Service Degraded | PostgreSQL or Mosquitto MQTT unreachable. |
