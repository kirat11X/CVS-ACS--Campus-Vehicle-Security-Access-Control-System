import { apiBase } from "../lib/platform";
import type {
  AlertItem,
  DashboardSummary,
  DeliveryDetail,
  DeliverySummary,
  FeedPage,
  Gate,
  GateCreate,
  GateUpdate,
  GuardDecision,
  HealthAll,
  ObservationCreate,
  WhatsAppStatus,
  InsideResponse,
  Lane,
  LaneUpsert,
  LoginResponse,
  ManualObservationCreate,
  MovementDetail,
  MovementDirection,
  MovementPage,
  OwnerContext,
  OwnerCreate,
  OwnerDetail,
  OwnerUpdate,
  ResolutionCreate,
  ResolvedObservation,
  UserAccount,
  UserCreate,
  UserSummary,
  UserUpdate,
  VehicleCreate,
  VehicleDetail,
  VehicleHistory,
  VehicleLinkRequest,
  VehicleLinkResponse,
  VehicleUpdate,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const REQUEST_TIMEOUT_MS = 20_000;

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI validation errors
      return detail
        .map((d) => {
          const loc = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
          return loc ? `${loc}: ${d?.msg}` : String(d?.msg ?? d);
        })
        .join("; ");
    }
  }
  return fallback;
}

let unauthorizedHandler: (() => void) | null = null;

/** Called on any 401 so the app can drop an expired session. */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}

/** Absolute or /api-relative URL for a backend path. */
export function apiUrl(path: string, base = apiBase()): string {
  if (!base) throw new ApiError(0, "No server address is set. Enter the console server address first.");
  return `${base}${path}`;
}

function timeoutSignal(signal?: AbortSignal): AbortSignal | undefined {
  if (signal) return signal; // caller-managed (feed, searches)
  return typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(REQUEST_TIMEOUT_MS) : undefined;
}

export async function request<T>(
  path: string,
  options: { method?: string; token?: string | null; body?: unknown; signal?: AbortSignal; base?: string } = {},
): Promise<T> {
  // FormData (file uploads) goes as multipart; the browser sets the boundary header itself.
  const multipart = options.body instanceof FormData;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined && !multipart) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = `Bearer ${options.token}`;

  let res: Response;
  try {
    res = await fetch(apiUrl(path, options.base), {
      method: options.method ?? "GET",
      headers,
      body: multipart ? (options.body as FormData) : options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: timeoutSignal(options.signal),
      cache: "no-store",
    });
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (options.signal?.aborted) throw err;
    const timedOut = err instanceof DOMException && err.name === "TimeoutError";
    throw new ApiError(0, timedOut ? "The server did not respond in time." : "Could not reach the server. Check the connection.");
  }

  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    if (res.status === 401 && options.token) notifyUnauthorized();
    throw new ApiError(res.status, detailMessage(body, `${res.status} ${res.statusText}`));
  }
  return body as T;
}

type Params = Record<string, string | number | boolean | undefined | null>;

export function query(params: Params): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

const enc = encodeURIComponent;

export const api = {
  // ---- Auth ----
  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", { method: "POST", body: { username, password } }),
  me: (token: string) => request<UserSummary>("/auth/me", { token }),
  changePassword: (token: string, body: { current_password: string; new_password: string }) =>
    request<null>("/auth/password", { method: "POST", token, body }),

  // ---- Health (no auth) ----
  health: (base?: string, signal?: AbortSignal) => request<{ status: string }>("/health", { base, signal }),
  healthAll: (signal?: AbortSignal) => request<HealthAll>("/health/all", { signal }),

  // ---- Live feed ----
  feed: (token: string, sinceId?: number, signal?: AbortSignal) =>
    request<FeedPage>(sinceId === undefined ? "/feed?limit=100" : `/feed?since_id=${sinceId}&limit=200`, { token, signal }),
  snapshot: async (token: string, observationId: string, signal?: AbortSignal): Promise<{ blob: Blob | null; status: number }> => {
    const res = await fetch(apiUrl(`/feed/snapshots/${observationId}`), { headers: { Authorization: `Bearer ${token}` }, signal });
    if (res.status === 401) notifyUnauthorized();
    return { blob: res.ok ? await res.blob() : null, status: res.status };
  },

  // ---- Dashboard ----
  dashboard: (token: string, since: string) => request<DashboardSummary>(`/dashboard/summary${query({ since })}`, { token }),

  // ---- Gates & lanes ----
  gates: () => request<Gate[]>("/gates"),
  createGate: (token: string, body: GateCreate) => request<Gate>("/gates", { method: "POST", token, body }),
  updateGate: (token: string, id: string, body: GateUpdate) => request<Gate>(`/gates/${enc(id)}`, { method: "PUT", token, body }),
  deactivateGate: (token: string, id: string) => request<{ message: string }>(`/gates/${enc(id)}`, { method: "DELETE", token }),
  lanes: (token: string) => request<Lane[]>("/lanes", { token }),
  upsertLane: (token: string, cameraId: string, body: LaneUpsert) =>
    request<Lane>(`/lanes/${enc(cameraId)}`, { method: "PUT", token, body }),

  // ---- Owners ----
  searchOwners: (token: string, q: string, signal?: AbortSignal, personType?: string | null) =>
    request<OwnerContext[]>(`/owners${query({ q, person_type: personType })}`, { token, signal }),
  owners: (token: string, params: Params) => request<OwnerContext[]>(`/owners${query(params)}`, { token }),
  owner: (token: string, id: string) => request<OwnerDetail>(`/owners/${enc(id)}`, { token }),
  createOwner: (token: string, body: OwnerCreate) => request<OwnerContext>("/owners", { method: "POST", token, body }),
  updateOwner: (token: string, id: string, body: OwnerUpdate) =>
    request<OwnerDetail>(`/owners/${enc(id)}`, { method: "PUT", token, body }),
  deleteOwner: (token: string, id: string) =>
    request<{ status: string; message: string; deleted_id: string }>(`/owners/${enc(id)}`, { method: "DELETE", token }),

  // ---- Vehicles ----
  vehicles: (token: string, params: Params) => request<VehicleDetail[]>(`/vehicles${query(params)}`, { token }),
  vehicle: (token: string, plate: string) => request<VehicleDetail>(`/vehicles/${enc(plate)}`, { token }),
  registerVehicle: (token: string, body: VehicleCreate) => request<VehicleDetail>("/vehicles", { method: "POST", token, body }),
  updateVehicle: (token: string, plate: string, body: VehicleUpdate) =>
    request<VehicleDetail>(`/vehicles/${enc(plate)}`, { method: "PUT", token, body }),
  deactivateVehicle: (token: string, plate: string) =>
    request<{ message: string; vehicle_status: string }>(`/vehicles/${enc(plate)}`, { method: "DELETE", token }),
  history: (token: string, plate: string, signal?: AbortSignal) =>
    request<VehicleHistory>(`/vehicles/${enc(plate)}/history`, { token, signal }),
  linkVehicle: (token: string, plate: string, body: VehicleLinkRequest) =>
    request<VehicleLinkResponse>(`/vehicles/${enc(plate)}/link`, { method: "POST", token, body }),

  // ---- Observations & guard actions ----
  logManualObservation: (token: string, body: ManualObservationCreate) =>
    request<ResolvedObservation>("/observations/manual", { method: "POST", token, body }),
  recordResolution: (token: string, body: ResolutionCreate) =>
    request<{ item: ResolvedObservation }>("/resolutions", { method: "POST", token, body }),

  // ---- Movement log & presence ----
  confirmMovement: (token: string, body: { observation_id: string; direction: MovementDirection; note?: string | null }) =>
    request<MovementDetail>("/logs/confirm", { method: "POST", token, body }),
  correctMovement: (token: string, logId: string, body: { direction?: MovementDirection; plate?: string; note: string }) =>
    request<MovementDetail>(`/logs/${logId}/corrections`, { method: "POST", token, body }),
  logs: (token: string, params: Params, signal?: AbortSignal) => request<MovementPage>(`/logs${query(params)}`, { token, signal }),
  logDetail: (token: string, logId: string) => request<MovementDetail>(`/logs/${logId}`, { token }),
  inside: (token: string, signal?: AbortSignal) => request<InsideResponse>("/presence/inside", { token, signal }),

  // ---- Users (ADMIN) ----
  users: (token: string, params: Params) => request<UserAccount[]>(`/users${query(params)}`, { token }),
  createUser: (token: string, body: UserCreate) => request<UserAccount>("/users", { method: "POST", token, body }),
  updateUser: (token: string, id: string, body: UserUpdate) =>
    request<UserAccount>(`/users/${id}`, { method: "PATCH", token, body }),

  // ---- Test sightings (ADMIN; cameras normally arrive over MQTT) ----
  recordObservation: (token: string, body: ObservationCreate) =>
    request<{ id: string }>("/observations", { method: "POST", token, body }),

  // ---- Delivery screening ----
  deliveries: (token: string, params: Params, signal?: AbortSignal) =>
    request<DeliverySummary[]>(`/deliveries${query(params)}`, { token, signal }),
  delivery: (token: string, orderId: string) => request<DeliveryDetail>(`/deliveries/${enc(orderId)}`, { token }),
  /** Invoice image via the authenticated route (an <img src> cannot carry the bearer token). */
  invoiceImage: async (token: string, orderId: string, signal?: AbortSignal): Promise<{ blob: Blob | null; status: number }> => {
    const res = await fetch(apiUrl(`/deliveries/${enc(orderId)}/invoice-image`), { headers: { Authorization: `Bearer ${token}` }, signal });
    if (res.status === 401) notifyUnauthorized();
    return { blob: res.ok ? await res.blob() : null, status: res.status };
  },
  processDelivery: (token: string, form: FormData) =>
    request<DeliveryDetail>("/deliveries/process", { method: "POST", token, body: form, signal: AbortSignal.timeout?.(120_000) }),
  decideDelivery: (token: string, orderId: string, body: { decision: GuardDecision; note?: string | null }) =>
    request<DeliveryDetail>(`/deliveries/${enc(orderId)}/decision`, { method: "POST", token, body }),
  deleteDelivery: (token: string, orderId: string) =>
    request<{ status: string; message: string; deleted_order_id: string }>(`/deliveries/${enc(orderId)}`, { method: "DELETE", token }),

  // ---- Alerts & messaging ----
  alerts: (token: string, limit: number, signal?: AbortSignal) => request<AlertItem[]>(`/alerts${query({ limit })}`, { token, signal }),
  whatsappStatus: (token: string) => request<WhatsAppStatus>("/system/whatsapp", { token }),
};
