import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import type { Role, VehicleHistory } from "../api/types";
import {
  DIRECTION_REASON,
  LINK_STATUS_LABEL,
  METHOD_LABEL,
  MOVEMENT_LABEL,
  PRESENCE_LABEL,
  formatDateTime,
  formatPercent,
  humanize,
} from "../lib/format";
import { navigate } from "../lib/route";
import { inputClass, primaryButton, secondaryButton } from "./Modal";
import { FlagChips } from "./movement/FlagChips";
import { LinkOwnerModal } from "./movement/LinkOwnerModal";
import { MovementLabel } from "./movement/MovementLabel";

interface Props {
  token: string;
  role: Role;
  plate: string | null;
  notify: (m: string) => void;
}

export function VehicleHistoryPage({ token, role, plate, notify }: Props) {
  const [input, setInput] = useState(plate ?? "");
  const [history, setHistory] = useState<VehicleHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [linking, setLinking] = useState(false);

  const load = useCallback(async () => {
    if (!plate) {
      setHistory(null);
      return;
    }
    setLoading(true);
    try {
      setHistory(await api.history(token, plate));
      setError(null);
    } catch (e) {
      setHistory(null);
      setError(e instanceof ApiError ? e.message : "Could not load the history.");
    } finally {
      setLoading(false);
    }
  }, [token, plate]);

  useEffect(() => {
    setInput(plate ?? "");
    void load();
  }, [plate, load]);

  const search = (e: FormEvent) => {
    e.preventDefault();
    if (input.trim()) navigate("history", input.trim().toUpperCase());
  };

  return (
    <div className="space-y-4">
      <form onSubmit={search} className="flex max-w-md gap-2">
        <input
          className={inputClass + " font-mono uppercase"}
          placeholder="Plate, e.g. PB65AB1234"
          aria-label="Plate"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" className={primaryButton}>
          Show history
        </button>
      </form>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-slate-700">{error}</p>}
      {!plate && !loading && <p className="text-sm text-slate-500">Enter a plate to see its movements and sightings across all gates.</p>}

      {history && (
        <>
          <section className="rounded-lg bg-white p-4 ring-1 ring-slate-200">
            <div className="flex flex-wrap items-start gap-4">
              <div className="mr-auto">
                <div className="font-mono text-2xl font-semibold tracking-wider text-slate-900">{history.normalized_plate}</div>
                {history.owner ? (
                  <p className="text-sm text-slate-700">
                    {history.owner.name} · {history.owner.institutional_id} · {humanize(history.residence?.person_type)}
                    {history.residence?.residence_type ? ` · ${humanize(history.residence.residence_type)}` : ""}
                    {history.residence?.residence ? `, ${history.residence.residence}` : ""}
                  </p>
                ) : (
                  <p className="text-sm text-slate-600">{history.registered ? "Registered, no owner on record" : "Not in the registry"}</p>
                )}
                {history.vehicle && (
                  <p className="text-xs text-slate-500">
                    {humanize(history.vehicle.category)} · Registry status: {history.vehicle.registry_status}
                  </p>
                )}
              </div>
              <div className="text-right">
                <div className="text-sm font-medium text-slate-900">{PRESENCE_LABEL[history.presence.status]}</div>
                {history.presence.last_movement && (
                  <div className="text-xs text-slate-500">
                    {MOVEMENT_LABEL[history.presence.last_movement.direction]} at {history.presence.last_movement.gate.name},{" "}
                    {formatDateTime(history.presence.last_movement.timestamp)}
                  </div>
                )}
                <div className="mt-1">
                  <FlagChips flags={history.presence.flags} />
                </div>
              </div>
            </div>
            {!history.registered && (
              <button type="button" className={secondaryButton + " mt-3 text-xs"} onClick={() => setLinking(true)}>
                Link to owner
              </button>
            )}
            {history.link_events.length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-600">
                {history.link_events.map((l) => (
                  <li key={l.id}>
                    Linked {formatDateTime(l.linked_at)} by {l.linked_by.full_name} ({humanize(l.method)}): “{l.evidence_note}”
                    {l.expires_at ? ` · expires ${formatDateTime(l.expires_at)}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="mb-2 text-sm font-semibold text-slate-900">Timeline · all gates ({history.timeline.length})</h2>
            {history.timeline.length === 0 ? (
              <p className="text-sm text-slate-500">No movements or sightings recorded for this plate.</p>
            ) : (
              <ol className="divide-y divide-slate-100 rounded-lg bg-white ring-1 ring-slate-200">
                {history.timeline.map((t) => (
                  <li key={(t.movement?.id ?? t.sighting?.observation.id) as string} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                    <span className="w-44 shrink-0 text-xs tabular-nums text-slate-600">{formatDateTime(t.time)}</span>
                    <span className="w-40 shrink-0 text-xs text-slate-700">{t.gate.name}</span>
                    {t.movement ? (
                      <>
                        <MovementLabel direction={t.movement.direction} method={t.movement.direction_method} corrected={t.movement.corrected} />
                        <FlagChips flags={t.movement.flags} hide={["CORRECTED"]} />
                      </>
                    ) : t.sighting ? (
                      <span className="text-slate-700">
                        Seen
                        {t.sighting.direction && t.sighting.direction.direction !== "UNKNOWN"
                          ? ` · ${MOVEMENT_LABEL[t.sighting.direction.direction]} (${METHOD_LABEL[t.sighting.direction.method]}), repeat not logged`
                          : ` · direction unknown${
                              typeof t.sighting.direction?.evidence?.reason === "string"
                                ? ` (${DIRECTION_REASON[t.sighting.direction.evidence.reason as string] ?? "no declared source"})`
                                : ""
                            }`}
                        <span className="ml-2 text-xs text-slate-500">
                          {LINK_STATUS_LABEL[t.sighting.link_status]} · plate {formatPercent(t.sighting.observation.plate.confidence)}
                        </span>
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}

      {linking && history && (
        <LinkOwnerModal
          token={token}
          role={role}
          plate={history.normalized_plate}
          onClose={() => setLinking(false)}
          onLinked={(message) => {
            setLinking(false);
            notify(message);
            void load();
          }}
        />
      )}
    </div>
  );
}
