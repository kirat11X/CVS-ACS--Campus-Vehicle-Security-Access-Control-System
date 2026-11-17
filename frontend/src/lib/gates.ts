import type { Gate, Lane } from "../api/types";
import { LANE_ROLE_LABEL } from "./format";

/** Where a gate's movement direction comes from: a declared lane role or zone order, else nothing. */
export function directionSource(gate: Gate, lanes: Lane[]): { label: string; declared: boolean; extra: Lane[] } {
  const active = lanes.filter((l) => l.is_active && l.gate_id === gate.id);
  const own = active.find((l) => l.camera_id === gate.camera_id);
  const extra = active.filter((l) => l.camera_id !== gate.camera_id);
  if (!gate.camera_id) return { label: "No camera mapped", declared: false, extra };
  if (!own) return { label: "No lane role declared · sightings stay direction-unknown", declared: false, extra };
  if (own.lane_role === "BIDIRECTIONAL")
    return own.outside_zone && own.inside_zone
      ? { label: `Two-way · zones ${own.outside_zone} → ${own.inside_zone}`, declared: true, extra }
      : { label: "Two-way without zones · direction-unknown", declared: false, extra };
  return { label: LANE_ROLE_LABEL[own.lane_role], declared: true, extra };
}
