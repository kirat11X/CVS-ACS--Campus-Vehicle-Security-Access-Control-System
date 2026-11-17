import { cx } from "../../lib/cx";

/** A plate outline in a rounded tile. Purely a mark: it implies no barrier control. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cx("h-8 w-8 shrink-0", className)} aria-hidden>
      <rect width="32" height="32" rx="8" className="fill-slate-900 dark:fill-slate-100" />
      <rect x="6" y="10.5" width="20" height="11" rx="2.5" fill="none" strokeWidth="2" className="stroke-sky-400 dark:stroke-sky-600" />
      <path d="M10.5 16h1.5M15.25 16h1.5M20 16h1.5" strokeWidth="1.75" strokeLinecap="round" className="stroke-white dark:stroke-slate-900" />
    </svg>
  );
}

export function Logo({ subtitle = true }: { subtitle?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <LogoMark />
      <div className="min-w-0 leading-tight">
        <div className="truncate text-sm font-semibold text-slate-900 dark:text-white">Gate Console</div>
        {subtitle && <div className="truncate text-[11px] text-slate-500 dark:text-slate-400">Campus vehicle security</div>}
      </div>
    </div>
  );
}
