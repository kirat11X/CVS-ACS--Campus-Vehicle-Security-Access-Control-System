import { Camera, ImageOff, Keyboard } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { FeedObservation } from "../../api/types";
import { cx } from "../../lib/cx";
import { formatDateTime } from "../../lib/format";
import { Dialog } from "../ui/Dialog";

// Avoid re-asking for what is known to be missing: observations Frigate has no image for,
// and a short back-off while Frigate itself is unreachable (the proxy answers 502).
const missing = new Set<string>();
const FRIGATE_BACKOFF_MS = 60_000;
let frigateDownUntil = 0;

/** Camera snapshot via the authenticated backend proxy (an <img src> cannot carry the bearer token). */
export function SnapshotImage({ token, observation, className }: { token: string; observation: FeedObservation; className?: string }) {
  const skip = !observation.has_snapshot || missing.has(observation.id) || Date.now() < frigateDownUntil;
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "none">(skip ? "none" : "loading");
  const [enlarged, setEnlarged] = useState(false);

  useEffect(() => {
    if (skip) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    api
      .snapshot(token, observation.id, controller.signal)
      .then(({ blob, status }) => {
        if (!blob) {
          if (status === 502 || status === 504) frigateDownUntil = Date.now() + FRIGATE_BACKOFF_MS;
          else if (status === 404) missing.add(observation.id);
          setState("none");
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        setState("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("none");
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, observation.id, skip]);

  const manual = observation.source === "MANUAL";
  const frame = cx(
    "flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100 ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700",
    className ?? "h-20 w-28 sm:h-24 sm:w-36",
  );

  if (state === "ready" && url) {
    return (
      <>
        <button
          type="button"
          className={cx(frame, "group relative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500")}
          onClick={() => setEnlarged(true)}
          aria-label={`Enlarge camera snapshot at ${observation.gate.name}`}
        >
          <img src={url} alt="" className="h-full w-full object-cover transition-transform group-hover:scale-105" />
        </button>
        {enlarged && (
          <Dialog
            title={`${observation.plate.normalized ?? "No plate read"} · ${observation.gate.name}`}
            description={`${formatDateTime(observation.observed_at)} · camera ${observation.camera_id ?? "—"}`}
            onClose={() => setEnlarged(false)}
            size="xl"
          >
            <img src={url} alt={`Camera snapshot at ${observation.gate.name}`} className="w-full rounded-lg" />
          </Dialog>
        )}
      </>
    );
  }

  return (
    <div className={frame}>
      <span className="flex flex-col items-center gap-1 px-2 text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
        {manual ? <Keyboard className="h-4 w-4" aria-hidden /> : state === "loading" ? <Camera className="h-4 w-4 animate-pulse" aria-hidden /> : <ImageOff className="h-4 w-4" aria-hidden />}
        {manual ? "Manual entry" : state === "loading" ? "Loading…" : "No snapshot"}
      </span>
    </div>
  );
}
