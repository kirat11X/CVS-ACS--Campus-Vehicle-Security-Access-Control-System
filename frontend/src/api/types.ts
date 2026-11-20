// Mirrors backend/app/schemas/*.py (feed, vehicle, owner, gate, movement, dashboard, user, delivery, alert).

export type Role = "ADMIN" | "SUPERVISOR" | "GUARD";

export type LinkStatus = "LINKED" | "LINKED_INACTIVE" | "NOT_LINKED" | "LOW_CONFIDENCE" | "NO_PLATE";
export type LinkBasis = "EXACT_PLATE" | "GUARD_CONFIRMED";
export type Direction = "ENTRY" | "EXIT" | "UNKNOWN";
export type ObservationSource = "FRIGATE" | "MANUAL" | "OTHER";
export type ResolutionOutcome = "VEHICLE_CONFIRMED" | "NONE_OF_THESE";
export type FeedKind =
  | "SNAPSHOT"
  | "OBSERVATION_CREATED"
  | "OBSERVATION_UPDATED"
  | "RESOLUTION_ADDED"
  | "REGISTRY_UPDATED"
  | "MOVEMENT_UPDATED";

export type VehicleCategory =
  | "STUDENT"
  | "FACULTY"
  | "STAFF"
  | "RESIDENT"
  | "VISITOR"
  | "DELIVERY"
  | "RIDE_HAILING"
  | "UNKNOWN";
export type PersonType = "STUDENT" | "FACULTY" | "STAFF" | "RESIDENT";
export type ResidenceType = "HOSTELLER" | "DAY_SCHOLAR" | "OFF_CAMPUS" | "UNKNOWN";

export interface UserSummary {
  id: string;
  username: string;
  full_name: string;
  role: Role;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: UserSummary;
}

export interface FeedObservation {
  id: string;
  gate: { id: string; name: string };
  camera_id: string | null;
  observed_at: string;
  updated_at: string;
  source: ObservationSource;
  source_event_id: string | null;
  plate: { raw: string | null; normalized: string | null; confidence: number | null };
  vehicle_observation: { type: string; confidence: number | null };
  direction: Direction;
  note: string | null;
  created_by: UserSummary | null;
  update_count: number;
  has_snapshot: boolean;
  metadata_payload?: Record<string, any> | null;
}

export interface LinkedVehicle {
  id: string;
  plate: string;
  raw_plate: string;
  category: VehicleCategory;
  registry_status: string;
  is_active: boolean;
  make_model: string | null;
  color: string | null;
  valid_from: string | null;
  valid_until: string | null;
}

export interface OwnerContext {
  id: string;
  institutional_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  person_type: string | null;
  residence_type: string | null;
  residence: string | null;
  department: string | null;
  status: string;
  vehicle_plates?: string[];
  vehicle_count?: number;
}

export interface ResidenceInfo {
  person_type: string | null;
  residence_type: string | null;
  residence: string | null;
  department: string | null;
}

export interface RegistrySuggestion {
  vehicle_id: string;
  plate: string;
  raw_plate: string;
  similarity: number;
  category: VehicleCategory;
  registry_status: string;
  owner_name: string | null;
}

export interface ResolutionSummary {
  id: string;
  outcome: ResolutionOutcome;
  chosen_vehicle_id: string | null;
  note: string | null;
  created_by: UserSummary;
  created_at: string;
}

export type DirectionMethod = "CAMERA_ROLE" | "ZONE_ORDER" | "GUARD_CONFIRMED" | "NONE";
export type MovementDirection = "ENTRY" | "EXIT";
export type MovementStatus = "LOGGED" | "REPEAT_NOT_LOGGED" | "DIRECTION_UNKNOWN";

export interface DirectionInfo {
  direction: Direction;
  method: DirectionMethod;
  confidence: number | null;
  evidence: Record<string, unknown>;
}

export interface MovementSummary {
  id: string;
  direction: MovementDirection;
  method: DirectionMethod;
  timestamp: string;
  normalized_plate: string | null;
  corrected: boolean;
  created_by: UserSummary | null;
  note: string | null;
}

export interface ResolvedObservation {
  observation: FeedObservation;
  link_status: LinkStatus;
  link_basis: LinkBasis | null;
  vehicle: LinkedVehicle | null;
  owner: OwnerContext | null;
  residence: ResidenceInfo | null;
  suggestions: RegistrySuggestion[];
  resolution: ResolutionSummary | null;
  flags: string[];
  direction: DirectionInfo | null;
  movement: MovementSummary | null;
  movement_status: MovementStatus | null;
}

export interface FeedEntry {
  kind: FeedKind;
  cursor: number;
  item: ResolvedObservation;
}

export interface FeedPage {
  cursor: number;
  has_more: boolean;
  entries: FeedEntry[];
}

export type GateStatus = "ACTIVE" | "MAINTENANCE" | "LOCKED" | "OFFLINE" | "INACTIVE";

export interface Gate {
  id: string;
  name: string;
  location: string | null;
  status: GateStatus;
  camera_id: string | null;
  direction_capability: string;
  created_at: string;
  updated_at: string;
}

export interface GateCreate {
  id: string;
  name: string;
  location?: string | null;
  status?: GateStatus;
  camera_id?: string | null;
  direction_capability?: string;
}

export interface GateUpdate {
  name?: string;
  location?: string | null;
  status?: GateStatus;
  camera_id?: string | null;
  direction_capability?: string;
}

export interface VehicleCreate {
  plate: string;
  vehicle_category: VehicleCategory;
  owner_id?: string | null;
  make_model?: string | null;
  color?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  notes?: string | null;
}

export interface OwnerCreate {
  identifier: string;
  full_name: string;
  email?: string | null;
  phone?: string | null;
  person_type: PersonType;
  residence_type: ResidenceType;
  residence?: string | null;
  department?: string | null;
}

export type ObservedVehicleType = "CAR" | "MOTORCYCLE" | "BUS" | "TRUCK" | "BICYCLE" | "UNKNOWN";

export interface ManualObservationCreate {
  gate_id: string;
  plate?: string;
  direction: Direction;
  vehicle_type?: ObservedVehicleType;
  note?: string | null;
  is_visitor?: boolean;
  visitor_name?: string | null;
  visitor_phone?: string | null;
  place_of_visit?: string | null;
  reference_person?: string | null;
  allowed_duration_hours?: number | null;
}

export interface ResolutionCreate {
  observation_id: string;
  chosen_vehicle_id: string | "none";
  note?: string | null;
}

// ---- Phase 6: movement log, presence, history, linking ----

export type PresenceStatus = "INSIDE" | "OUTSIDE" | "UNKNOWN";

export interface MovementEntry {
  id: string;
  observation_id: string | null;
  gate: { id: string; name: string };
  timestamp: string;
  direction: MovementDirection;
  direction_method: DirectionMethod;
  direction_confidence: number | null;
  plate: string | null;
  normalized_plate: string | null;
  plate_source: "OBSERVATION" | "GUARD_CORRECTION" | null;
  linked: boolean;
  link_basis: string | null;
  vehicle: LinkedVehicle | null;
  owner: OwnerContext | null;
  residence: ResidenceInfo | null;
  flags: string[];
  corrected: boolean;
  correction_count: number;
  recorded_by: UserSummary | null;
  last_corrected_by: UserSummary | null;
  note: string | null;
}

export interface MovementPage {
  total: number;
  skip: number;
  limit: number;
  items: MovementEntry[];
}

export interface MovementLogRow {
  id: string;
  correction_of_id: string | null;
  direction: MovementDirection;
  direction_method: DirectionMethod;
  direction_confidence: number | null;
  direction_evidence: Record<string, unknown>;
  plate: string | null;
  normalized_plate: string | null;
  plate_source: "OBSERVATION" | "GUARD_CORRECTION" | null;
  plate_confidence: number | null;
  recorded_vehicle_id: string | null;
  created_by: UserSummary | null;
  created_at: string;
  note: string | null;
}

export interface MovementDetail {
  movement: MovementEntry;
  rows: MovementLogRow[];
}

export interface PresenceEntry {
  subject: string;
  status: PresenceStatus;
  normalized_plate: string | null;
  linked: boolean;
  vehicle: LinkedVehicle | null;
  owner: OwnerContext | null;
  residence: ResidenceInfo | null;
  last_movement: MovementEntry | null;
  inside_since: string | null;
  flags: string[];
}

export interface InsideResponse {
  total: number;
  items: PresenceEntry[];
  unattributed_entries: MovementEntry[];
}

export interface LinkEvent {
  id: string;
  vehicle_id: string;
  owner_id: string;
  method: "GUARD_VERIFIED_ID" | "ADMIN";
  evidence_note: string;
  linked_by: UserSummary;
  linked_at: string;
  expires_at: string | null;
}

export interface TimelineItem {
  type: "MOVEMENT" | "SIGHTING";
  time: string;
  gate: { id: string; name: string };
  movement: MovementEntry | null;
  sighting: ResolvedObservation | null;
}

export interface VehicleHistory {
  plate: string;
  normalized_plate: string;
  registered: boolean;
  vehicle: LinkedVehicle | null;
  owner: OwnerContext | null;
  residence: ResidenceInfo | null;
  presence: PresenceEntry;
  timeline: TimelineItem[];
  link_events: LinkEvent[];
}

export interface NewOwnerForLink {
  person_type: PersonType;
  identifier: string;
  full_name: string;
  residence_type: ResidenceType;
  residence?: string | null;
  department?: string | null;
}

export interface VehicleLinkRequest {
  owner_id?: string | null;
  new_owner?: NewOwnerForLink | null;
  vehicle_category: VehicleCategory;
  valid_from?: string | null;
  valid_until?: string | null;
  evidence_note: string;
  make_model?: string | null;
  color?: string | null;
}

export interface VehicleLinkResponse {
  vehicle: VehicleDetail;
  link_event: LinkEvent;
  retroactive: { movements: number; sightings: number };
}

// ---- Registry detail (GET /vehicles, GET /vehicles/{plate}) ----

export type VehicleStatus = "ACTIVE" | "INACTIVE" | "EXPIRED" | "SUSPENDED" | "BLACKLISTED";

export interface VehicleRecord {
  id: string;
  plate: string;
  raw_plate: string;
  category: VehicleCategory;
  status: VehicleStatus;
  is_active: boolean;
  make_model: string | null;
  color: string | null;
  valid_from: string | null;
  valid_until: string | null;
  notes: string | null;
}

export interface VehicleDetail {
  vehicle: VehicleRecord;
  owner: OwnerContext | null;
  context: {
    person_type: string | null;
    residence_type: string | null;
    residence: string | null;
    department: string | null;
    is_active: boolean;
    vehicle_status: string;
  };
}

export interface VehicleUpdate {
  owner_id?: string | null;
  vehicle_category?: VehicleCategory;
  status?: VehicleStatus;
  make_model?: string | null;
  color?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  notes?: string | null;
}

// ---- Owners (GET /owners/{id}, PUT /owners/{id}) ----

export interface OwnerDetail {
  owner: OwnerContext;
  vehicles: VehicleDetail[];
}

export interface OwnerUpdate {
  full_name?: string;
  email?: string | null;
  phone?: string | null;
  person_type?: PersonType;
  residence_type?: ResidenceType;
  residence?: string | null;
  department?: string | null;
}

// ---- Camera lanes ----

export type LaneRole = "ENTRY_LANE" | "EXIT_LANE" | "BIDIRECTIONAL";

export interface Lane {
  camera_id: string;
  gate_id: string;
  lane_role: LaneRole;
  outside_zone: string | null;
  inside_zone: string | null;
  is_active: boolean;
  notes: string | null;
  updated_at: string;
}

export interface LaneUpsert {
  gate_id: string;
  lane_role: LaneRole;
  outside_zone?: string | null;
  inside_zone?: string | null;
  is_active: boolean;
  notes?: string | null;
}

// ---- Users (ADMIN) ----

export interface UserAccount {
  id: string;
  username: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserCreate {
  username: string;
  full_name: string;
  email: string;
  role: Role;
  password: string;
}

export interface UserUpdate {
  full_name?: string;
  email?: string;
  role?: Role;
  is_active?: boolean;
  password?: string;
}

// ---- Dashboard ----

export interface ActivityBucket {
  start: string;
  observations: number;
  entries: number;
  exits: number;
}

export interface DashboardSummary {
  since: string;
  generated_at: string;
  bucket_minutes: number;
  observations: { total: number; camera: number; manual: number; without_plate: number; low_confidence_unresolved: number };
  movements: { entries: number; exits: number };
  presence: { inside: number; inside_linked: number; inside_unlinked: number; long_stay: number; unattributed_entries: number };
  registry: {
    vehicles: number;
    vehicles_by_status: Record<string, number>;
    vehicles_by_category: Record<string, number>;
    temporary_active: number;
    owners: number;
  };
  activity: ActivityBucket[];
  /** Deliveries whose overall verdict is REVIEW / ALERT and that no guard has decided yet. */
  delivery_flags?: number;
}

// ---- Delivery screening (invoices via local intake / WhatsApp / console) ----

/** Deterministic policy outcome per invoice line; OCR / ML never decides. */
export type Verdict = "ALLOW" | "REVIEW" | "ALERT";
export type GuardDecision = "CLEARED" | "HELD" | "ESCALATED";
export type DeliverySource = "LOCAL_INTAKE" | "WHATSAPP" | "CONSOLE";

export interface DeliveryDecision {
  decision: GuardDecision;
  note: string | null;
  by: string;
  at: string;
}

export interface DeliverySummary {
  order_id: string;
  platform: string | null;
  gate_id: string | null;
  source: DeliverySource;
  sender: string | null;
  received_at: string;
  line_count: number;
  review_count: number;
  alert_count: number;
  overall: Verdict;
  totals_match: boolean | null;
  total_amount: number | null;
  latest_decision: DeliveryDecision | null;
  reply_text: string;
}

export interface DeliveryLine {
  line_no: number;
  item_name: string;
  quantity: number | null;
  amount: number | null;
  category: string;
  category_label: string;
  reason_code: string;
  verdict: Verdict;
  confidence: number | null;
}

export interface DeliveryInvoice {
  image_url: string | null;
  ocr_engine: string | null;
  ocr_confidence: number | null;
  raw_ocr_text: string | null;
  vendor: string | null;
  subtotal: number | null;
  delivery_fee: number | null;
  total: number | null;
  computed_total: number | null;
}

export interface DeliveryDetail extends DeliverySummary {
  invoice: DeliveryInvoice;
  items: DeliveryLine[];
  decisions: DeliveryDecision[];
}

// ---- Alerts (GET /alerts) ----

export type AlertKind = "PLATE_REVIEW" | "PLATE_UNLINKED" | "DELIVERY_REVIEW" | "DELIVERY_ALERT" | "OVERSTAY_UNLINKED";
export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH";

export interface AlertItem {
  kind: AlertKind;
  severity: AlertSeverity;
  title: string;
  detail: string;
  ref: string;
  gate_id: string | null;
  at: string;
}

// ---- Messaging provider (GET /system/whatsapp) ----

export interface WhatsAppStatus {
  provider: "local" | "mock" | "meta" | string;
  available: boolean;
  intake_url: string;
  outbox_count: number;
}

// ---- Admin-only test sighting (POST /observations) ----

export interface ObservationCreate {
  gate_id: string;
  camera_id?: string | null;
  source: "FRIGATE" | "OTHER";
  source_event_id?: string | null;
  raw_plate?: string | null;
  plate_confidence?: number | null;
  vehicle_type?: ObservedVehicleType;
  direction?: Direction;
}

// ---- Health (GET /health/all) ----

export interface ComponentHealth {
  status: string;
  detail?: unknown;
  [key: string]: unknown;
}

export interface HealthAll {
  status: "ok" | "degraded";
  database: ComponentHealth;
  mqtt: ComponentHealth;
  frigate_worker: { running: boolean; connected: boolean; topic: string; stats: Record<string, number> };
  whatsapp_mock?: { status: string; available: boolean };
}

// ---- Multi-Gate Camera Stream Settings (Phase 13 / Stage 1) ----

export interface GateStreamConfigItem {
  gate_id: string;
  gate_name?: string | null;
  enabled: boolean;
  ip_address: string;
  port: number;
  protocol: "http" | "rtsp" | string;
  stream_path: string;
  custom_url?: string | null;
  stream_url: string;
  is_running: boolean;
  effective_fps: number;
  actual_fps: number;
  last_seen_at?: string | null;
  last_error?: string | null;
}

export interface GateStreamSettingsResponse {
  total_fps_budget: number;
  active_gates_count: number;
  per_gate_target_fps: number;
  gates: GateStreamConfigItem[];
}

export interface GateStreamConfigUpdateItem {
  gate_id: string;
  gate_name?: string | null;
  enabled?: boolean;
  ip_address?: string;
  port?: number;
  protocol?: string;
  stream_path?: string;
  custom_url?: string | null;
}

export interface GateStreamSettingsUpdate {
  total_fps_budget?: number;
  gates?: GateStreamConfigUpdateItem[];
}

export interface StreamTestRequest {
  ip_address?: string;
  port?: number;
  protocol?: string;
  stream_path?: string;
  custom_url?: string | null;
}

export interface StreamTestResponse {
  status: "ok" | "error";
  gate_id?: string | null;
  tested_url: string;
  latency_ms?: number | null;
  stream_type?: string | null;
  message: string;
}
