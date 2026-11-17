import { ArrowLeftFromLine, ArrowRightToLine } from "lucide-react";
import type { DirectionMethod, MovementDirection } from "../../api/types";
import { METHOD_LABEL, MOVEMENT_LABEL } from "../../lib/format";

/** "→ Entered campus · camera role" */
export function MovementLabel({ direction, method, corrected }: { direction: MovementDirection; method: DirectionMethod; corrected?: boolean }) {
  const Icon = direction === "ENTRY" ? ArrowRightToLine : ArrowLeftFromLine;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
      <Icon className="h-3.5 w-3.5 shrink-0 text-slate-500 dark:text-slate-400" aria-hidden />
      <span className="font-medium text-slate-900 dark:text-slate-100">{MOVEMENT_LABEL[direction]}</span>
      <span className="text-slate-500 dark:text-slate-400">· {METHOD_LABEL[method]}</span>
      {corrected && <span className="text-[11px] text-slate-500 dark:text-slate-400">(corrected)</span>}
    </span>
  );
}
