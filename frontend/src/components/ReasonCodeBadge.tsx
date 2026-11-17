import {
  AlertOctagon,
  AlertTriangle,
  Ban,
  CheckCircle2,
  HelpCircle,
  PackageX,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import type { LinkStatus, LinkedVehicle } from "../api/types";
import { cx } from "../lib/cx";
import { Badge } from "./ui/Feedback";

export type StandardReasonCode =
  | "ALLOW_REGISTERED_VEHICLE"
  | "REVIEW_LOW_CONFIDENCE_PLATE"
  | "REVIEW_UNKNOWN_VEHICLE"
  | "ALERT_RESTRICTED_ITEM"
  | "ALERT_BLACKLISTED_VEHICLE"
  | string;

interface ReasonCodeConfig {
  label: string;
  shortLabel: string;
  tone: "green" | "yellow" | "red" | "slate";
  icon: ReactNode;
  hint: string;
}

const KNOWN_CODES: Record<string, ReasonCodeConfig> = {
  ALLOW_REGISTERED_VEHICLE: {
    label: "ALLOW · Registered Vehicle",
    shortLabel: "ALLOW · Registered",
    tone: "green",
    icon: <ShieldCheck className="h-3 w-3" aria-hidden />,
    hint: "Vehicle is officially registered in campus database with active validity.",
  },
  REVIEW_LOW_CONFIDENCE_PLATE: {
    label: "REVIEW · Low Confidence Plate (< 70%)",
    shortLabel: "REVIEW · Low Plate Conf",
    tone: "yellow",
    icon: <AlertTriangle className="h-3 w-3" aria-hidden />,
    hint: "Camera OCR confidence is below threshold (< 0.70). Manual visual confirmation needed.",
  },
  REVIEW_UNKNOWN_VEHICLE: {
    label: "REVIEW · Unknown Vehicle",
    shortLabel: "REVIEW · Unknown",
    tone: "yellow",
    icon: <HelpCircle className="h-3 w-3" aria-hidden />,
    hint: "License plate not matched to any active campus registration or owner.",
  },
  ALERT_RESTRICTED_ITEM: {
    label: "ALERT · Restricted Item",
    shortLabel: "ALERT · Restricted",
    tone: "red",
    icon: <PackageX className="h-3 w-3" aria-hidden />,
    hint: "Invoice or cargo contains restricted/prohibited goods requiring physical search or refusal.",
  },
  ALERT_BLACKLISTED_VEHICLE: {
    label: "ALERT · Blacklisted Vehicle",
    shortLabel: "ALERT · Blacklisted",
    tone: "red",
    icon: <Ban className="h-3 w-3" aria-hidden />,
    hint: "Vehicle is explicitly barred from campus entry by administration.",
  },
};

const TONE_CLASSES: Record<"green" | "yellow" | "red" | "slate", string> = {
  green:
    "bg-emerald-50 text-emerald-800 ring-emerald-600/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30",
  yellow:
    "bg-amber-50 text-amber-900 ring-amber-600/30 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/40",
  red:
    "bg-rose-50 text-rose-800 ring-rose-600/30 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30",
  slate:
    "bg-slate-100 text-slate-700 ring-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
};

export function getReasonCodeConfig(code: string): ReasonCodeConfig {
  if (KNOWN_CODES[code]) {
    return KNOWN_CODES[code];
  }

  // Fallbacks based on prefix
  if (code.startsWith("ALLOW_")) {
    return {
      label: code.replace(/_/g, " "),
      shortLabel: code.replace("ALLOW_", "ALLOW · "),
      tone: "green",
      icon: <CheckCircle2 className="h-3 w-3" aria-hidden />,
      hint: `Policy outcome: Allowed (${code})`,
    };
  }

  if (code.startsWith("REVIEW_")) {
    return {
      label: code.replace(/_/g, " "),
      shortLabel: code.replace("REVIEW_", "REVIEW · "),
      tone: "yellow",
      icon: <AlertTriangle className="h-3 w-3" aria-hidden />,
      hint: `Policy outcome: Guard Review Required (${code})`,
    };
  }

  if (code.startsWith("ALERT_") || code.includes("RESTRICTED") || code.includes("BLACKLIST")) {
    return {
      label: code.replace(/_/g, " "),
      shortLabel: code.replace("ALERT_", "ALERT · "),
      tone: "red",
      icon: <AlertOctagon className="h-3 w-3" aria-hidden />,
      hint: `Policy outcome: Security Alert (${code})`,
    };
  }

  return {
    label: code.replace(/_/g, " "),
    shortLabel: code,
    tone: "slate",
    icon: <ShieldAlert className="h-3 w-3" aria-hidden />,
    hint: `Reason code: ${code}`,
  };
}

export interface ReasonCodeBadgeProps {
  code: StandardReasonCode | null | undefined;
  compact?: boolean;
  showIcon?: boolean;
  className?: string;
}

export function ReasonCodeBadge({
  code,
  compact = false,
  showIcon = true,
  className,
}: ReasonCodeBadgeProps) {
  if (!code) return null;

  const cfg = getReasonCodeConfig(code);
  const toneClass = TONE_CLASSES[cfg.tone];

  return (
    <Badge
      className={cx(
        "font-mono text-[10px] tracking-tight transition-colors",
        toneClass,
        className,
      )}
      title={`${cfg.hint} [Code: ${code}]`}
    >
      {showIcon && cfg.icon}
      <span>{compact ? cfg.shortLabel : cfg.label}</span>
    </Badge>
  );
}

/**
 * Determines the authoritative reason code for an observation or vehicle sighting.
 */
export function determineReasonCode(params: {
  plateConfidence?: number | null;
  linkStatus?: LinkStatus;
  vehicle?: LinkedVehicle | null;
  flags?: string[];
  isRestricted?: boolean;
  status?: string | null;
}): StandardReasonCode {
  const { plateConfidence, linkStatus, vehicle, flags = [], isRestricted, status } = params;

  // 1. Blacklisted vehicle (highest security priority)
  if (
    vehicle?.registry_status === "BLACKLISTED" ||
    status === "BLACKLISTED" ||
    flags.includes("BLACKLISTED") ||
    flags.includes("ALERT_BLACKLISTED_VEHICLE")
  ) {
    return "ALERT_BLACKLISTED_VEHICLE";
  }

  // 2. Prohibited or restricted items
  if (
    isRestricted ||
    flags.includes("ALERT_RESTRICTED_ITEM") ||
    flags.includes("RESTRICTED_ITEM") ||
    flags.includes("PROHIBITED_GOODS")
  ) {
    return "ALERT_RESTRICTED_ITEM";
  }

  // 3. Low confidence plate read (< 0.70)
  if (
    linkStatus === "LOW_CONFIDENCE" ||
    (plateConfidence !== null && plateConfidence !== undefined && plateConfidence < 0.7)
  ) {
    return "REVIEW_LOW_CONFIDENCE_PLATE";
  }

  // 4. Unknown / unregistered vehicle
  if (
    linkStatus === "NOT_LINKED" ||
    linkStatus === "NO_PLATE" ||
    !vehicle ||
    vehicle.category === "UNKNOWN" ||
    flags.includes("UNKNOWN_VEHICLE")
  ) {
    return "REVIEW_UNKNOWN_VEHICLE";
  }

  // 5. Default allowed registered vehicle
  return "ALLOW_REGISTERED_VEHICLE";
}
