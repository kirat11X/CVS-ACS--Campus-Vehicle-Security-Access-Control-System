import type {
  AlertKind,
  AlertSeverity,
  DeliverySource,
  DirectionMethod,
  GuardDecision,
  LaneRole,
  LinkStatus,
  MovementDirection,
  PresenceStatus,
  Verdict,
} from "../api/types";

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatShortTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

export function formatFeedTimestamp(iso: string, includeSeconds = false): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  const timeStr = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: includeSeconds ? "2-digit" : undefined,
  });

  if (isToday) return `Today, ${timeStr}`;
  if (isYesterday) return `Yesterday, ${timeStr}`;
  const sameYear = d.getFullYear() === now.getFullYear();
  const dateStr = d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: sameYear ? undefined : "numeric",
  });
  return `${dateStr}, ${timeStr}`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

/** 1,284 · 12.9K · 4.2M */
export function compactNumber(n: number): string {
  return new Intl.NumberFormat(undefined, { notation: n >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(n);
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

/** datetime-local input value for a Date, in local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** "3 h 5 min" style duration since iso. */
export function formatSince(iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - Date.parse(iso)) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

/** "just now", "4 min ago", "3 h ago", else the date. */
export function formatRelative(iso: string, now = Date.now()): string {
  const seconds = Math.round((now - Date.parse(iso)) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDateTime(iso);
}

// Wording follows the guard console slides: LINKED / UNLINKED / NEEDS REVIEW.
export const LINK_STATUS_LABEL: Record<LinkStatus, string> = {
  LINKED: "Linked",
  LINKED_INACTIVE: "Linked · inactive registration",
  NOT_LINKED: "Unlinked · not in registry",
  LOW_CONFIDENCE: "Needs review · uncertain read",
  NO_PLATE: "No plate read",
};

export const LINK_STATUS_SHORT: Record<LinkStatus, string> = {
  LINKED: "Linked",
  LINKED_INACTIVE: "Inactive registration",
  NOT_LINKED: "Unlinked",
  LOW_CONFIDENCE: "Needs review",
  NO_PLATE: "No plate",
};

/** Upper-case pill text used in the live plate list. */
export const LINK_STATUS_PILL: Record<LinkStatus, string> = {
  LINKED: "LINKED",
  LINKED_INACTIVE: "LINKED · INACTIVE",
  NOT_LINKED: "UNLINKED",
  LOW_CONFIDENCE: "NEEDS REVIEW",
  NO_PLATE: "NO PLATE",
};

export const LINK_STATUS_HINT: Record<LinkStatus, string> = {
  LINKED: "Plate matches an active registry entry.",
  LINKED_INACTIVE: "Plate matches a registry entry whose status or validity is not active.",
  NOT_LINKED: "No registry entry for this plate. Unknown is not a threat; it is logged.",
  LOW_CONFIDENCE: "Camera read is uncertain. Compare the close registry matches and confirm one.",
  NO_PLATE: "The camera did not read a plate.",
};

// Neutral palette. Not linked is plain slate (never red); nothing uses
// green/red semantics, which would read as a pass/stop signal.
export const LINK_STATUS_STYLE: Record<LinkStatus, { badge: string; edge: string; dot: string }> = {
  LINKED: {
    badge: "bg-sky-50 text-sky-900 ring-sky-300 dark:bg-sky-500/15 dark:text-sky-200 dark:ring-sky-500/40",
    edge: "border-l-sky-500",
    dot: "bg-sky-500",
  },
  LINKED_INACTIVE: {
    badge: "bg-violet-50 text-violet-900 ring-violet-300 dark:bg-violet-500/15 dark:text-violet-200 dark:ring-violet-500/40",
    edge: "border-l-violet-400",
    dot: "bg-violet-400",
  },
  NOT_LINKED: {
    badge: "bg-slate-100 text-slate-800 ring-slate-300 dark:bg-slate-700/40 dark:text-slate-200 dark:ring-slate-600",
    edge: "border-l-slate-400 dark:border-l-slate-500",
    dot: "bg-slate-400",
  },
  LOW_CONFIDENCE: {
    badge: "bg-amber-50 text-amber-900 ring-amber-300 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/40",
    edge: "border-l-amber-400",
    dot: "bg-amber-400",
  },
  NO_PLATE: {
    badge: "bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-700/40 dark:text-zinc-300 dark:ring-zinc-600",
    edge: "border-l-zinc-300 dark:border-l-zinc-600",
    dot: "bg-zinc-400",
  },
};

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

export const LANE_ROLE_LABEL: Record<LaneRole, string> = {
  ENTRY_LANE: "Entry lane",
  EXIT_LANE: "Exit lane",
  BIDIRECTIONAL: "Two-way",
};

/** Registry status exactly as recorded. Only BLACKLISTED (an administrator's record) stands out. */
export function registryStatusTone(status: string): string {
  if (status === "BLACKLISTED") return "bg-rose-50 text-rose-900 ring-rose-300 dark:bg-rose-500/15 dark:text-rose-200 dark:ring-rose-500/40";
  if (status === "ACTIVE") return "bg-slate-50 text-slate-700 ring-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-600";
  return "bg-violet-50 text-violet-900 ring-violet-300 dark:bg-violet-500/15 dark:text-violet-200 dark:ring-violet-500/40";
}

// ---- Delivery screening ----
// Invoice verdicts are policy-table outcomes for the guard to read, not access decisions, so they
// use the slides' green / amber / red. Plate linkage above stays neutral (unknown != threat).
export const VERDICT_STYLE: Record<Verdict, { badge: string; dot: string; edge: string }> = {
  ALLOW: {
    badge: "bg-emerald-50 text-emerald-900 ring-emerald-300 dark:bg-emerald-500/15 dark:text-emerald-200 dark:ring-emerald-500/40",
    dot: "bg-emerald-500",
    edge: "border-l-emerald-500",
  },
  REVIEW: {
    badge: "bg-amber-50 text-amber-900 ring-amber-300 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/40",
    dot: "bg-amber-400",
    edge: "border-l-amber-400",
  },
  ALERT: {
    badge: "bg-rose-50 text-rose-900 ring-rose-300 dark:bg-rose-500/15 dark:text-rose-200 dark:ring-rose-500/40",
    dot: "bg-rose-500",
    edge: "border-l-rose-500",
  },
};

export const DECISION_LABEL: Record<GuardDecision, string> = {
  CLEARED: "Cleared",
  HELD: "Held",
  ESCALATED: "Escalated",
};

export const DELIVERY_SOURCE_LABEL: Record<DeliverySource, string> = {
  LOCAL_INTAKE: "Local intake",
  WHATSAPP: "WhatsApp",
  CONSOLE: "Console upload",
};

export const ALERT_KIND_LABEL: Record<AlertKind, string> = {
  PLATE_REVIEW: "Plate needs review",
  PLATE_UNLINKED: "Unlinked plate",
  DELIVERY_REVIEW: "Delivery to review",
  DELIVERY_ALERT: "Delivery alert",
  OVERSTAY_UNLINKED: "Unlinked vehicle overstay",
};

export const SEVERITY_STYLE: Record<AlertSeverity, string> = {
  HIGH: VERDICT_STYLE.ALERT.badge,
  MEDIUM: VERDICT_STYLE.REVIEW.badge,
  LOW: "bg-slate-100 text-slate-700 ring-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-600",
};

/** 675 -> "675.00" (invoice amounts as printed). */
export function formatAmount(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

/** "GATE_2" -> "G2"; other ids keep the gate name. */
export function gateShort(gate: { id: string; name: string }): string {
  const m = /^GATE_(\d+)$/i.exec(gate.id);
  return m ? `G${m[1]}` : gate.name;
}

/** "GATE_2" -> "Gate 2"; other ids keep the gate name. */
export function gateLabel(gate: { id: string; name: string }): string {
  const m = /^GATE_(\d+)$/i.exec(gate.id);
  return m ? `Gate ${m[1]}` : gate.name;
}

/** "24103042" -> "2410••••", "F1002014" -> "F100••••", "R1042" -> "R1042": the feed list protects PII. */
export function maskReference(id: string | null | undefined): string {
  if (!id) return "—";
  const clean = id.trim();
  if (/^[Rr]\d{4}$/.test(clean)) return clean.toUpperCase();
  if (clean.length === 8) return `${clean.slice(0, 4)}••••`;
  const keep = Math.max(2, clean.length - 4);
  return `${clean.slice(0, keep)}${"•".repeat(clean.length - keep)}`;
}

/**
 * How a read differs from a registry plate when they are one edit apart, e.g.
 * ("CH01AB11234", "CH01AB1234") -> "after removing 1 extra character". null when not one edit.
 */
export function describeOneEdit(read: string, plate: string): string | null {
  if (read === plate) return "exact match";
  if (Math.abs(read.length - plate.length) > 1) return null;
  if (read.length === plate.length) {
    let diff = 0;
    for (let i = 0; i < read.length; i++) if (read[i] !== plate[i]) diff++;
    return diff === 1 ? "after correcting 1 misread character" : null;
  }
  const [longer, shorter] = read.length > plate.length ? [read, plate] : [plate, read];
  for (let i = 0; i < longer.length; i++) {
    if (longer.slice(0, i) + longer.slice(i + 1) === shorter) {
      return read.length > plate.length ? "after removing 1 extra character" : "after adding 1 missing character";
    }
  }
  return null;
}

export const GATE_STATUS_STYLE: Record<string, string> = {
  ACTIVE: "bg-sky-50 text-sky-900 ring-sky-300 dark:bg-sky-500/15 dark:text-sky-200 dark:ring-sky-500/40",
  MAINTENANCE: "bg-amber-50 text-amber-900 ring-amber-300 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/40",
  LOCKED: "bg-violet-50 text-violet-900 ring-violet-300 dark:bg-violet-500/15 dark:text-violet-200 dark:ring-violet-500/40",
  OFFLINE: "bg-zinc-100 text-zinc-700 ring-zinc-300 dark:bg-zinc-700/40 dark:text-zinc-300 dark:ring-zinc-600",
  INACTIVE: "bg-zinc-100 text-zinc-500 ring-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700",
};
