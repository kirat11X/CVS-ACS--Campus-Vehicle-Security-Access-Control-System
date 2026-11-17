import { AlertCircle, Info, Loader2, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "../../api/client";
import { cx } from "../../lib/cx";
import { Button } from "./Button";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" className={cx("inline-flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400", className)}>
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-md bg-slate-200/80 dark:bg-slate-800", className)} aria-hidden />;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-col items-center px-6 py-12 text-center", className)}>
      {icon && (
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold text-slate-900 dark:text-white">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function errorMessage(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const forbidden = error instanceof ApiError && error.status === 403;
  return (
    <div className={cx("flex flex-col items-center px-6 py-10 text-center", className)} role="alert">
      <AlertCircle className="mb-2 h-6 w-6 text-slate-400" aria-hidden />
      <p className="text-sm font-semibold text-slate-900 dark:text-white">{forbidden ? "Not available for your role" : "Could not load this"}</p>
      <p className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{errorMessage(error)}</p>
      {onRetry && !forbidden && (
        <Button size="sm" className="mt-4" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-800 ring-1 ring-slate-300 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden />
      <span>{message}</span>
    </p>
  );
}

export function Callout({ children, tone = "info", title }: { children: ReactNode; tone?: "info" | "notice"; title?: string }) {
  return (
    <div
      className={cx(
        "flex gap-3 rounded-xl px-4 py-3 text-sm ring-1",
        tone === "notice"
          ? "bg-amber-50 text-amber-950 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-100 dark:ring-amber-500/30"
          : "bg-sky-50 text-sky-950 ring-sky-200 dark:bg-sky-500/10 dark:text-sky-100 dark:ring-sky-500/30",
      )}
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 opacity-70" aria-hidden />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        <div className={cx(title && "mt-0.5", "opacity-90")}>{children}</div>
      </div>
    </div>
  );
}

export function Badge({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset", className)}>
      {children}
    </span>
  );
}
