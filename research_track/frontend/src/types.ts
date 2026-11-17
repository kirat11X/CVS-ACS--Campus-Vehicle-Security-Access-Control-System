export interface Observation {
  id: string;
  plate: string | null;
  confidence: number | null;
  vehicleType: string;
  direction: "ENTRY" | "EXIT" | "UNKNOWN";
  observedAt: string;
  gateId?: string;
}

export interface VehicleDetail {
  plate: string;
  normalizedPlate: string;
  vehicleType: string;
  color?: string;
  status: string;
  owner?: {
    name: string;
    personType: string;
    residenceType?: string;
    hostelRoom?: string;
    address?: string;
    department?: string;
  };
}

export interface ScreeningItem {
  item: string;
  category: string;
  confidence: number | null;
  rule: string;
  reasonCode: string;
  outcome: "ALLOW" | "REVIEW" | "ALERT";
}

export interface PolicyRule {
  id: string;
  category: string;
  action: "ALLOW" | "REVIEW" | "ALERT";
  condition: string;
  reasonCode: string;
  priority: number;
  policyVersion: string;
  active: boolean;
}

export interface EvalMetrics {
  track: string;
  model: string;
  dataset: string;
  status: string;
  note: string;
  [key: string]: unknown;
}

export interface Gate {
  id: string;
  name: string;
  location: string;
  status: string;
  cameraId: string;
}
