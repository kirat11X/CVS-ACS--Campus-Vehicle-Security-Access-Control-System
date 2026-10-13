import { FLAG_LABEL } from "../../lib/format";

/** Neutral context flags (slate chips; never alarm colours). */
export function FlagChips({ flags, hide = [] }: { flags: string[]; hide?: string[] }) {
  const shown = flags.filter((f) => !hide.includes(f));
  if (shown.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {shown.map((f) => (
        <span key={f} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700 ring-1 ring-slate-300">
          {FLAG_LABEL[f] ?? f}
        </span>
      ))}
    </span>
  );
}
