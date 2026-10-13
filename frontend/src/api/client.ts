import type {
  FeedPage,
  Gate,
  InsideResponse,
  MovementDetail,
  MovementDirection,
  MovementPage,
  VehicleHistory,
  VehicleLinkRequest,
  VehicleLinkResponse,
  LoginResponse,
  ManualObservationCreate,
  OwnerContext,
  OwnerCreate,
  ResolutionCreate,
  ResolvedObservation,
  UserSummary,
  VehicleCreate,
} from "./types";

export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

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

export async function request<T>(
  path: string,
  options: { method?: string; token?: string | null; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = `Bearer ${options.token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    cache: "no-store",
  });

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

function query(params: Record<string, string | number | boolean | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  return q.toString();
}

export const api = {
  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", { method: "POST", body: { username, password } }),
  me: (token: string) => request<UserSummary>("/auth/me", { token }),

  feed: (token: string, sinceId?: number, signal?: AbortSignal) =>
    request<FeedPage>(sinceId === undefined ? "/feed?limit=100" : `/feed?since_id=${sinceId}&limit=200`, {
      token,
      signal,
    }),

  gates: () => request<Gate[]>("/gates"),

  searchOwners: (token: string, q: string, signal?: AbortSignal) =>
    request<OwnerContext[]>(`/owners?q=${encodeURIComponent(q)}`, { token, signal }),
  createOwner: (token: string, body: OwnerCreate) =>
    request<OwnerContext>("/owners", { method: "POST", token, body }),

  registerVehicle: (token: string, body: VehicleCreate) =>
    request<unknown>("/vehicles", { method: "POST", token, body }),

  logManualObservation: (token: string, body: ManualObservationCreate) =>
    request<ResolvedObservation>("/observations/manual", { method: "POST", token, body }),

  recordResolution: (token: string, body: ResolutionCreate) =>
    request<{ item: ResolvedObservation }>("/resolutions", { method: "POST", token, body }),

  confirmMovement: (token: string, body: { observation_id: string; direction: MovementDirection; note?: string | null }) =>
    request<MovementDetail>("/logs/confirm", { method: "POST", token, body }),
  correctMovement: (token: string, logId: string, body: { direction?: MovementDirection; plate?: string; note: string }) =>
    request<MovementDetail>(`/logs/${logId}/corrections`, { method: "POST", token, body }),
  logs: (token: string, params: Record<string, string | number | boolean | undefined>, signal?: AbortSignal) =>
    request<MovementPage>(`/logs?${query(params)}`, { token, signal }),
  logDetail: (token: string, logId: string) => request<MovementDetail>(`/logs/${logId}`, { token }),
  inside: (token: string, signal?: AbortSignal) => request<InsideResponse>("/presence/inside", { token, signal }),
  history: (token: string, plate: string, signal?: AbortSignal) =>
    request<VehicleHistory>(`/vehicles/${encodeURIComponent(plate)}/history`, { token, signal }),
  linkVehicle: (token: string, plate: string, body: VehicleLinkRequest) =>
    request<VehicleLinkResponse>(`/vehicles/${encodeURIComponent(plate)}/link`, { method: "POST", token, body }),

  snapshot: async (token: string, observationId: string, signal?: AbortSignal): Promise<Blob | null> => {
    const res = await fetch(`${API_BASE}/feed/snapshots/${observationId}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    });
    if (res.status === 401) notifyUnauthorized();
    return res.ok ? res.blob() : null;
  },
};
