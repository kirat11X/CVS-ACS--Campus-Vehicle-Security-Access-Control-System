import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { InsideResponse } from "../api/types";
import { formatDateTime, formatSince, formatTime } from "../lib/format";
import { secondaryButton } from "./Modal";
import { CorrectionModal, type CorrectionTarget } from "./movement/CorrectionModal";
import { FlagChips } from "./movement/FlagChips";
import { MovementLabel } from "./movement/MovementLabel";
import { SubjectCell } from "./movement/SubjectCell";

const REFRESH_MS = 15_000;

export function InsidePage({ token, notify }: { token: string; notify: (m: string) => void }) {
  const [data, setData] = useState<InsideResponse | null>(null);
  const [linked, setLinked] = useState<"all" | "linked" | "unlinked">("all");
  const [error, setError] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<CorrectionTarget | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.inside(token));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load presence.");
    }
  }, [token]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const items = (data?.items ?? []).filter((e) => linked === "all" || (linked === "linked") === e.linked);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-sm font-semibold text-slate-900">
          Inside campus <span className="font-normal text-slate-500">({data?.total ?? "…"})</span>
        </h2>
        {(["all", "linked", "unlinked"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setLinked(v)}
            className={`rounded-full px-2.5 py-1 text-xs ring-1 ${linked === v ? "bg-slate-800 text-white ring-slate-800" : "bg-white text-slate-700 ring-slate-300"}`}
          >
            {v === "all" ? "All" : v === "linked" ? "Linked" : "Not linked"}
          </button>
        ))}
        <button type="button" className={secondaryButton + " px-2 py-1 text-xs"} onClick={() => void load()}>
          Refresh
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Derived from the latest recorded movement of each vehicle. A vehicle is listed when its last movement is an entry.
      </p>
      {error && <p className="text-sm text-slate-700">{error}</p>}

      <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Vehicle</th>
              <th className="px-3 py-2">Entered</th>
              <th className="px-3 py-2">Inside for</th>
              <th className="px-3 py-2">Gate</th>
              <th className="px-3 py-2">Context</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((e) => (
              <tr key={e.subject}>
                <td className="px-3 py-2">
                  <SubjectCell plate={e.normalized_plate} vehicle={e.vehicle} owner={e.owner} residence={e.residence} />
                </td>
                <td className="px-3 py-2 text-xs text-slate-700" title={e.inside_since ? formatDateTime(e.inside_since) : undefined}>
                  {e.last_movement && <MovementLabel direction={e.last_movement.direction} method={e.last_movement.direction_method} />}
                  <div className="text-slate-500">{e.inside_since ? formatDateTime(e.inside_since) : "—"}</div>
                </td>
                <td className="px-3 py-2 text-xs tabular-nums text-slate-700">{e.inside_since ? formatSince(e.inside_since) : "—"}</td>
                <td className="px-3 py-2 text-xs text-slate-700">{e.last_movement?.gate.name ?? "—"}</td>
                <td className="px-3 py-2">
                  <FlagChips flags={e.flags} />
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-sm text-slate-500">
                  {data ? "No vehicles recorded inside." : "Loading…"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {data && data.unattributed_entries.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">Entries without a plate read (last 24 h)</h3>
          <p className="text-xs text-slate-500">These cannot be paired with an exit until a plate is added.</p>
          <ul className="divide-y divide-slate-100 rounded-lg bg-white ring-1 ring-slate-200">
            {data.unattributed_entries.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                <span className="tabular-nums text-slate-700">{formatTime(m.timestamp)}</span>
                <span className="text-slate-600">{m.gate.name}</span>
                <MovementLabel direction={m.direction} method={m.direction_method} />
                <button
                  type="button"
                  className={secondaryButton + " ml-auto px-2 py-1 text-xs"}
                  onClick={() => setCorrecting({ movementId: m.id, direction: m.direction, plate: null })}
                >
                  Add plate
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {correcting && (
        <CorrectionModal
          token={token}
          target={correcting}
          onClose={() => setCorrecting(null)}
          onCorrected={() => {
            setCorrecting(null);
            notify("Correction recorded.");
            void load();
          }}
        />
      )}
    </div>
  );
}
