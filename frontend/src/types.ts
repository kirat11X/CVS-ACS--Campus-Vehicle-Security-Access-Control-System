// Comprehensive TypeScript definitions for CVS-ACS Guard & Security Console.
// Re-exports all API models and provides specialized types for Review Queue,
// Delivery Verification, Reason Codes, and Audit Logging.

export * from "./api/types";

export type ReasonCode =
  | "ALLOW_REGISTERED_VEHICLE"
  | "REVIEW_LOW_CONFIDENCE_PLATE"
  | "REVIEW_UNKNOWN_VEHICLE"
  | "ALERT_RESTRICTED_ITEM"
  | "ALERT_BLACKLISTED_VEHICLE"
  | string;

export type TriageAction = "ALLOW" | "DENY" | "OVERRIDE";

export interface TriageAuditRecord {
  id: string;
  eventId: string;
  action: TriageAction;
  reasonCode: ReasonCode;
  guardName: string;
  notes?: string | null;
  timestamp: string;
}

export type TriageCategoryFilter =
  | "ALL"
  | "LOW_CONFIDENCE"
  | "UNKNOWN_VEHICLE"
  | "UNAPPROVED_VISITOR"
  | "POLICY_ALERT";

export interface DeliveryTriageAction {
  orderId: string;
  action: "APPROVE_OPEN" | "FLAG_SEARCH" | "DENY";
  notes?: string;
  timestamp: string;
  guardName: string;
}
