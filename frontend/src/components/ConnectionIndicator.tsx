import type { ConnectionState } from "../feed/useLiveFeed";
import { formatTime } from "../lib/format";

const DISPLAY: Record<ConnectionState, { label: string; dot: string; detail: string }> = {
  connecting: { label: "Connecting", dot: "bg-slate-400 animate-pulse", detail: "Loading the feed" },
  live: { label: "Live", dot: "bg-sky-500", detail: "Receiving events as they happen" },
  reconnecting: { label: "Reconnecting", dot: "bg-amber-400 animate-pulse", detail: "Live stream dropped; retrying" },
  polling: { label: "Polling", dot: "bg-amber-500", detail: "Live stream unavailable; refreshing every 3 s" },
  offline: { label: "Offline", dot: "bg-slate-500", detail: "Backend unreachable; retrying" },
};

export function ConnectionIndicator({ state, lastSyncAt }: { state: ConnectionState; lastSyncAt: number | null }) {
  const d = DISPLAY[state];
  return (
    <div
      className="flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs text-slate-700 ring-1 ring-slate-200"
      title={d.detail}
      role="status"
      aria-live="polite"
    >
      <span className={`h-2.5 w-2.5 rounded-full ${d.dot}`} aria-hidden="true" />
      <span className="font-medium">{d.label}</span>
      {lastSyncAt && <span className="text-slate-500">· synced {formatTime(new Date(lastSyncAt).toISOString())}</span>}
    </div>
  );
}
