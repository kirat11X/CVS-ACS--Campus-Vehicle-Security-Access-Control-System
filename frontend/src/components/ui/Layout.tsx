import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { cx } from "../../lib/cx";
import { Button } from "./Button";

export function PageHeader({
  title,
  description,
  actions,
  back,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label: string };
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back && (
          <Link
            to={back.to}
            className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
            {back.label}
          </Link>
        )}
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 dark:border-slate-800 sm:px-5">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-slate-900 dark:text-white">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cx(bodyClassName ?? "p-4 sm:p-5")}>{children}</div>
    </section>
  );
}

export function DetailList({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={cx("grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3", className)}>{children}</dl>;
}

export function Detail({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  const empty = value === null || value === undefined || value === "";
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className={cx("mt-0.5 text-sm text-slate-900 dark:text-slate-100", mono ? "break-all font-mono" : "break-words")}>{empty ? "—" : value}</dd>
    </div>
  );
}

/** label · value · optional context line and trend (stat-tile contract). */
export function StatTile({
  label,
  value,
  sub,
  icon,
  to,
  trend,
  loading,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  to?: string;
  trend?: ReactNode;
  loading?: boolean;
}) {
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-slate-600 dark:text-slate-400">{label}</span>
        {icon && <span className="text-slate-400 dark:text-slate-500">{icon}</span>}
      </div>
      <div className={cx("mt-2 text-2xl font-semibold tracking-tight text-slate-900 dark:text-white sm:text-3xl", loading && "opacity-40")}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
      {trend && <div className="mt-2">{trend}</div>}
    </>
  );
  const cls = "card block p-4 transition-shadow";
  return to ? (
    <Link to={to} className={cx(cls, "hover:shadow-md hover:ring-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:hover:ring-slate-700")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

export function FilterChips<T extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: {
  options: { value: T; label: ReactNode; count?: number }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cx("-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 scrollbar-none sm:mx-0 sm:flex-wrap sm:px-0", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx("chip", value === o.value ? "chip-on" : "chip-off")}
        >
          {o.label}
          {o.count !== undefined && <span className={cx("tabular-nums", value === o.value ? "opacity-80" : "text-slate-500 dark:text-slate-400")}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Offset pagination; `total` when the API reports it, else "next" is enabled while pages are full. */
export function Pagination({
  skip,
  limit,
  count,
  total,
  onChange,
}: {
  skip: number;
  limit: number;
  count: number;
  total?: number;
  onChange: (skip: number) => void;
}) {
  const hasNext = total !== undefined ? skip + limit < total : count === limit;
  if (skip === 0 && !hasNext) return null;
  const end = skip + count;
  return (
    <nav className="flex items-center justify-between gap-3 px-1 py-3 text-xs text-slate-600 dark:text-slate-400" aria-label="Pagination">
      <span className="tabular-nums">
        {count === 0 ? "No results" : `${skip + 1}–${end}`}
        {total !== undefined && ` of ${total}`}
      </span>
      <div className="flex gap-2">
        <Button size="sm" disabled={skip === 0} onClick={() => onChange(Math.max(0, skip - limit))} icon={<ChevronLeft className="h-3.5 w-3.5" />}>
          Previous
        </Button>
        <Button size="sm" disabled={!hasNext} onClick={() => onChange(skip + limit)}>
          Next
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
