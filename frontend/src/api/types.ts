// Mirrors backend/app/schemas/feed.py, vehicle.py, owner.py and gate.py.

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

export interface Gate {
  id: string;
  name: string;
  location: string | null;
  status: string;
  camera_id: string | null;
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

export interface ManualObservationCreate {
  gate_id: string;
  plate: string;
  direction: Direction;
  note?: string | null;
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
  link_event: LinkEvent;
  retroactive: { movements: number; sightings: number };
}
