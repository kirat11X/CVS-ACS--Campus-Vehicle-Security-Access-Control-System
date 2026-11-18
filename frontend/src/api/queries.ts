import { keepPreviousData, QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useSession } from "../auth/AuthContext";
import { ApiError, api } from "./client";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        retry: (count, err) => !(err instanceof ApiError && [400, 401, 403, 404, 422].includes(err.status)) && count < 2,
      },
    },
  });
}

type Params = Record<string, string | number | boolean | undefined | null>;

export const qk = {
  dashboard: (since: string) => ["dashboard", since] as const,
  health: ["health"] as const,
  gates: ["gates"] as const,
  lanes: ["lanes"] as const,
  inside: ["inside"] as const,
  logs: (p: Params) => ["logs", p] as const,
  logDetail: (id: string) => ["logs", "detail", id] as const,
  history: (plate: string) => ["history", plate] as const,
  vehicles: (p: Params) => ["vehicles", p] as const,
  vehicle: (plate: string) => ["vehicle", plate] as const,
  owners: (p: Params) => ["owners", p] as const,
  owner: (id: string) => ["owner", id] as const,
  users: (p: Params) => ["users", p] as const,
  deliveries: (p: Params) => ["deliveries", p] as const,
  delivery: (orderId: string) => ["delivery", orderId] as const,
  alerts: (limit: number) => ["alerts", limit] as const,
  whatsapp: ["whatsapp"] as const,
  streamSettings: ["stream-settings"] as const,
};

/** Invalidate every query whose key starts with one of `roots` after a write. */
export function useInvalidate() {
  const client = useQueryClient();
  return useCallback(
    (...roots: string[]) => Promise.all(roots.map((root) => client.invalidateQueries({ queryKey: [root] }))),
    [client],
  );
}

/** Roots touched by a registry change (vehicle, owner or link). */
export const REGISTRY_ROOTS = ["vehicles", "vehicle", "history", "owners", "owner", "dashboard", "inside", "logs", "alerts"];
/** Roots touched by a movement confirmation or correction. */
export const MOVEMENT_ROOTS = ["logs", "inside", "history", "dashboard"];
/** Roots touched by a new invoice or a guard decision on a delivery. */
export const DELIVERY_ROOTS = ["deliveries", "delivery", "alerts", "dashboard"];

export function useDashboard(since: string) {
  const { token } = useSession();
  return useQuery({
    queryKey: qk.dashboard(since),
    queryFn: () => api.dashboard(token, since),
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useHealth(refetchInterval = 15_000) {
  return useQuery({ queryKey: qk.health, queryFn: ({ signal }) => api.healthAll(signal), refetchInterval, retry: false });
}

export function useGates() {
  return useQuery({ queryKey: qk.gates, queryFn: api.gates, staleTime: 60_000 });
}

export function useLanes() {
  const { token } = useSession();
  return useQuery({ queryKey: qk.lanes, queryFn: () => api.lanes(token), staleTime: 60_000 });
}

export function useInside() {
  const { token } = useSession();
  return useQuery({ queryKey: qk.inside, queryFn: ({ signal }) => api.inside(token, signal), refetchInterval: 15_000 });
}

export function useLogs(params: Params) {
  const { token } = useSession();
  return useQuery({
    queryKey: qk.logs(params),
    queryFn: ({ signal }) => api.logs(token, params, signal),
    placeholderData: keepPreviousData,
  });
}

export function useLogDetail(id: string | null) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.logDetail(id ?? ""), queryFn: () => api.logDetail(token, id!), enabled: !!id });
}

export function useHistory(plate: string | null) {
  const { token } = useSession();
  return useQuery({
    queryKey: qk.history(plate ?? ""),
    queryFn: ({ signal }) => api.history(token, plate!, signal),
    enabled: !!plate,
  });
}

export function useVehicles(params: Params) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.vehicles(params), queryFn: () => api.vehicles(token, params), placeholderData: keepPreviousData });
}

export function useVehicle(plate: string | null, enabled = true) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.vehicle(plate ?? ""), queryFn: () => api.vehicle(token, plate!), enabled: !!plate && enabled });
}

export function useOwners(params: Params) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.owners(params), queryFn: () => api.owners(token, params), placeholderData: keepPreviousData });
}

export function useOwner(id: string | null) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.owner(id ?? ""), queryFn: () => api.owner(token, id!), enabled: !!id });
}

export function useUsers(params: Params) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.users(params), queryFn: () => api.users(token, params), placeholderData: keepPreviousData });
}

export function useDeliveries(params: Params, refetchInterval: number | false = 20_000) {
  const { token } = useSession();
  return useQuery({
    queryKey: qk.deliveries(params),
    queryFn: ({ signal }) => api.deliveries(token, params, signal),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
}

export function useDelivery(orderId: string | null) {
  const { token } = useSession();
  return useQuery({ queryKey: qk.delivery(orderId ?? ""), queryFn: () => api.delivery(token, orderId!), enabled: !!orderId });
}

export function useAlerts(limit = 100, refetchInterval = 20_000) {
  const { token } = useSession();
  return useQuery({
    queryKey: qk.alerts(limit),
    queryFn: ({ signal }) => api.alerts(token, limit, signal),
    placeholderData: keepPreviousData,
    refetchInterval,
  });
}

export function useWhatsAppStatus() {
  const { token } = useSession();
  return useQuery({ queryKey: qk.whatsapp, queryFn: () => api.whatsappStatus(token), staleTime: 60_000, refetchInterval: 60_000 });
}

export function useStreamSettings(refetchInterval: number | false = 5000) {
  const { token } = useSession();
  return useQuery({
    queryKey: qk.streamSettings,
    queryFn: () => api.streamSettings(token),
    refetchInterval,
  });
}
