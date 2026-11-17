import type { GateStatus, PersonType, ResidenceType, Role, VehicleCategory, VehicleStatus } from "../../api/types";

export const ALL_CATEGORIES: VehicleCategory[] = ["STUDENT", "FACULTY", "STAFF", "RESIDENT", "VISITOR", "DELIVERY", "RIDE_HAILING", "UNKNOWN"];
// GUARD / SUPERVISOR may only register temporary entries with a validity window (enforced by the backend too).
export const TEMPORARY_CATEGORIES: VehicleCategory[] = ["VISITOR", "DELIVERY"];
export const PERSON_TYPES: PersonType[] = ["STUDENT", "FACULTY", "STAFF", "RESIDENT"];
export const RESIDENCE_TYPES: ResidenceType[] = ["HOSTELLER", "DAY_SCHOLAR", "OFF_CAMPUS", "UNKNOWN"];
export const VEHICLE_STATUSES: VehicleStatus[] = ["ACTIVE", "INACTIVE", "EXPIRED", "SUSPENDED", "BLACKLISTED"];
export const GATE_STATUSES: GateStatus[] = ["ACTIVE", "MAINTENANCE", "LOCKED", "OFFLINE", "INACTIVE"];
export const ROLES: Role[] = ["GUARD", "SUPERVISOR", "ADMIN"];

/** "" -> null, otherwise trimmed. */
export function blankToNull(value: string): string | null {
  const t = value.trim();
  return t ? t : null;
}

export interface IdentifierGuide {
  label: string;
  hint: string;
  placeholder: string;
  pattern?: string;
  maxLength: number;
}

export function getIdentifierGuide(personType: PersonType): IdentifierGuide {
  switch (personType) {
    case "STUDENT":
      return {
        label: "Student ID (SID)",
        hint: "Exactly 8 numeric digits (e.g. 24103042)",
        placeholder: "24103042",
        pattern: "^[0-9]{8}$",
        maxLength: 8,
      };
    case "FACULTY":
      return {
        label: "Faculty ID",
        hint: "Starts with 'F' + 7 digits (e.g. F1234567)",
        placeholder: "F1234567",
        pattern: "^[Ff][0-9]{7}$",
        maxLength: 8,
      };
    case "RESIDENT":
      return {
        label: "Resident ID (House No.)",
        hint: "Starts with 'R' + 4-digit house number (e.g. R1042)",
        placeholder: "R1042",
        pattern: "^[Rr][0-9]{4}$",
        maxLength: 5,
      };
    case "STAFF":
      return {
        label: "Staff ID",
        hint: "Institutional staff code (e.g. STF-EST-022)",
        placeholder: "STF-EST-022",
        maxLength: 50,
      };
    default:
      return {
        label: "Institutional ID",
        hint: "Institutional identifier",
        placeholder: "ID-12345",
        maxLength: 50,
      };
  }
}

export function validateIdentifier(identifier: string, personType: PersonType): string | null {
  const clean = identifier.trim();
  if (!clean) return "Identifier is required.";
  if (personType === "STUDENT" && !/^\d{8}$/.test(clean)) {
    return "Student ID must be exactly 8 numeric digits (e.g. 24103042).";
  }
  if (personType === "FACULTY" && !/^[Ff]\d{7}$/.test(clean)) {
    return "Faculty ID must start with 'F' followed by 7 digits (e.g. F1234567).";
  }
  if (personType === "RESIDENT" && !/^[Rr]\d{4}$/.test(clean)) {
    return "Resident ID must start with 'R' followed by a 4-digit house number (e.g. R1042).";
  }
  return null;
}
