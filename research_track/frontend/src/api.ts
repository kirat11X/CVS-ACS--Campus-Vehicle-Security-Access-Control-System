import mockData from "./mocks/data.json";
import type { Observation, VehicleDetail, ScreeningItem, PolicyRule, EvalMetrics, Gate } from "./types";

const useMocks = import.meta.env.VITE_USE_MOCKS !== "false";
const BASE = import.meta.env.VITE_API_BASE || "";

async function get<T>(path: string, fallback: T): Promise<T> {
  if (useMocks) return fallback;
  try {
    const res = await fetch(`${BASE}${path}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return (await res.json()) as T;
  } catch {
    console.warn(`API call failed for ${path}, using mock fallback`);
    return fallback;
  }
}

export const api = {
  health: () => get("/health/all", { status: "mock" }),
  vehicles: () => get<VehicleDetail[]>("/vehicles", []),
  vehicle: (plate: string) =>
    get<VehicleDetail | null>(`/vehicles/${encodeURIComponent(plate)}`, null),
  gates: () => get<Gate[]>("/gates", mockData.gates as Gate[]),
  observations: () =>
    get<Observation[]>("/observations", mockData.observations as Observation[]),
  screeningQueue: () =>
    get<ScreeningItem[]>(
      "/screening/invoices/review-queue",
      mockData.screening as ScreeningItem[]
    ),
  screeningPolicy: () =>
    get<PolicyRule[]>("/screening/policy-rules", mockData.policyRules as PolicyRule[]),
  evaluation: () =>
    get<EvalMetrics>("/ml/evaluations", mockData.metrics as EvalMetrics),
};
