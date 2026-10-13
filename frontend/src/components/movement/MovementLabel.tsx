import type { DirectionMethod, MovementDirection } from "../../api/types";
import { METHOD_LABEL, MOVEMENT_LABEL } from "../../lib/format";

/** "Entered campus · camera role" */
export function MovementLabel({ direction, method, corrected }: { direction: MovementDirection; method: DirectionMethod; corrected?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className="font-mono text-slate-500">
        {direction === "ENTRY" ? "→" : "←"}
      </span>
      <span className="font-medium text-slate-900">{MOVEMENT_LABEL[direction]}</span>
      <span className="text-slate-500">· {METHOD_LABEL[method]}</span>
      {corrected && <span className="text-[11px] text-slate-500">(corrected)</span>}
    </span>
  );
}
