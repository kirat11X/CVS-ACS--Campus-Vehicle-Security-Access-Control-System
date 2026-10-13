import type { DirectionMethod, LinkStatus, MovementDirection, PresenceStatus } from "../api/types";

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** datetime-local input value for a Date, in local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const LINK_STATUS_LABEL: Record<LinkStatus, string> = {
  LINKED: "Linked",
  LINKED_INACTIVE: "Linked · inactive registration",
  NOT_LINKED: "Not linked",
  LOW_CONFIDENCE: "Low-confidence read",
  NO_PLATE: "No plate read",
};

export const LINK_STATUS_HINT: Record<LinkStatus, string> = {
  LINKED: "Plate matches an active registry entry.",
  LINKED_INACTIVE: "Plate matches a registry entry whose status or validity is not active.",
  NOT_LINKED: "No registry entry for this plate.",
  LOW_CONFIDENCE: "Camera read is uncertain. Compare the candidates below.",
  NO_PLATE: "The camera did not read a plate.",
};

// Neutral palette. Not linked is plain slate (never red); nothing uses
// green/red semantics, which would read as a pass/stop signal.
export const LINK_STATUS_STYLE: Record<LinkStatus, { badge: string; edge: string }> = {
  LINKED: { badge: "bg-sky-100 text-sky-900 ring-sky-300", edge: "border-l-sky-500" },
  LINKED_INACTIVE: { badge: "bg-violet-100 text-violet-900 ring-violet-300", edge: "border-l-violet-400" },
  NOT_LINKED: { badge: "bg-slate-100 text-slate-800 ring-slate-300", edge: "border-l-slate-400" },
  LOW_CONFIDENCE: { badge: "bg-amber-100 text-amber-900 ring-amber-300", edge: "border-l-amber-400" },
  NO_PLATE: { badge: "bg-zinc-100 text-zinc-700 ring-zinc-300", edge: "border-l-zinc-300" },
};

/** "3 h 5 min" style duration since iso. */
export function formatSince(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

export const MOVEMENT_LABEL: Record<MovementDirection, string> = {
  ENTRY: "Entered campus",
  EXIT: "Left campus",
};

export const METHOD_LABEL: Record<DirectionMethod, string> = {
  CAMERA_ROLE: "camera role",
  ZONE_ORDER: "zone order",
  GUARD_CONFIRMED: "guard confirmed",
  NONE: "no declared source",
};

export const PRESENCE_LABEL: Record<PresenceStatus, string> = {
  INSIDE: "Inside campus",
  OUTSIDE: "Outside campus",
  UNKNOWN: "No movement recorded",
};

// Neutral context only. None of these is a judgement about the vehicle.
export const FLAG_LABEL: Record<string, string> = {
  EXIT_WITHOUT_ENTRY: "Exit with no recorded entry",
  ENTRY_WHILE_INSIDE: "Entry while already recorded inside",
  LONG_STAY: "Long stay",
  NO_PLATE: "No plate read",
  LOW_CONFIDENCE_PLATE: "Low-confidence plate",
  CORRECTED: "Corrected",
  VALIDITY_ENDED: "Validity window ended",
  VALIDITY_NOT_STARTED: "Validity window not started",
};

export const DIRECTION_REASON: Record<string, string> = {
  NO_LANE_CONFIG: "camera has no declared lane role",
  BIDIRECTIONAL_WITHOUT_ZONES: "two-way lane without declared zones",
  INSUFFICIENT_ZONE_EVIDENCE: "zone order not observed",
  LANE_GATE_MISMATCH: "lane is declared for another gate",
  GUARD_REPORTED_UNKNOWN: "logged by a guard as unknown",
  NO_CAMERA: "no camera recorded",
  UNSUPPORTED_SOURCE: "source has no direction",
};
