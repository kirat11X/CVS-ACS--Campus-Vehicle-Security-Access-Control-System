import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { FeedObservation } from "../api/types";

/** Camera snapshot via the authenticated backend proxy (an <img src> cannot carry the bearer token). */
export function SnapshotImage({ token, observation }: { token: string; observation: FeedObservation }) {
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "none">(observation.has_snapshot ? "loading" : "none");

  useEffect(() => {
    if (!observation.has_snapshot) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    api
      .snapshot(token, observation.id, controller.signal)
      .then((blob) => {
        if (!blob) {
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
  }, [token, observation.id, observation.has_snapshot]);

  const label =
    observation.source === "MANUAL" ? "Manual entry · no camera image" : state === "loading" ? "Loading snapshot…" : "No snapshot available";

  return (
    <div className="flex h-28 w-full shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100 ring-1 ring-slate-200 sm:h-24 sm:w-36">
      {state === "ready" && url ? (
        <img src={url} alt={`Camera snapshot at ${observation.gate.name}`} className="h-full w-full object-cover" />
      ) : (
        <span className="px-2 text-center text-xs text-slate-500">{label}</span>
      )}
    </div>
  );
}
