import type { ConnectionState } from "../../feed/useLiveFeed";
import { cx } from "../../lib/cx";
import { formatTime } from "../../lib/format";

export const CONNECTION_DISPLAY: Record<ConnectionState, { label: string; dot: string; detail: string }> = {
  connecting: { label: "Connecting", dot: "bg-slate-400 animate-pulse", detail: "Loading the feed" },
  live: { label: "Live", dot: "bg-sky-500", detail: "Receiving events as they happen" },
  reconnecting: { label: "Reconnecting", dot: "bg-amber-400 animate-pulse", detail: "Live stream dropped; retrying" },
  polling: { label: "Polling", dot: "bg-amber-500", detail: "Live stream unavailable; refreshing every 3 s" },
  offline: { label: "Offline", dot: "bg-slate-500", detail: "Backend unreachable; retrying" },
};

export function ConnectionIndicator({
  state,
  lastSyncAt,
  compact = false,
}: {
  state: ConnectionState;
  lastSyncAt: number | null;
  compact?: boolean;
}) {
  const d = CONNECTION_DISPLAY[state];
  return (
    <div
      className={cx(
        "inline-flex items-center gap-2 rounded-full bg-white text-xs text-slate-700 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700",
        compact ? "px-2.5 py-1" : "px-3 py-1",
      )}
      title={`${d.detail}${lastSyncAt ? ` · last synced ${formatTime(new Date(lastSyncAt).toISOString())}` : ""}`}
      role="status"
      aria-live="polite"
    >
      <span className={cx("h-2 w-2 rounded-full", d.dot)} aria-hidden />
      <span className="font-medium">{d.label}</span>
      {!compact && lastSyncAt && <span className="hidden text-slate-500 dark:text-slate-400 xl:inline">· {formatTime(new Date(lastSyncAt).toISOString())}</span>}
    </div>
  );
}
