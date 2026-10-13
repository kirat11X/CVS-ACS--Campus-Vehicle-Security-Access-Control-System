import { Fragment, useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import type { Gate, MovementDetail, MovementPage } from "../api/types";
import { METHOD_LABEL, MOVEMENT_LABEL, formatDateTime } from "../lib/format";
import { navigate } from "../lib/route";
import { Field, inputClass, primaryButton, secondaryButton } from "./Modal";
import { CorrectionModal, type CorrectionTarget } from "./movement/CorrectionModal";
import { FlagChips } from "./movement/FlagChips";
import { MovementLabel } from "./movement/MovementLabel";
import { SubjectCell } from "./movement/SubjectCell";

const PAGE_SIZE = 50;

interface Filters {
  plate: string;
  gate_id: string;
  direction: string;
  date_from: string;
  date_to: string;
  linked: string;
}

const EMPTY: Filters = { plate: "", gate_id: "", direction: "", date_from: "", date_to: "", linked: "" };

function toIso(local: string): string | undefined {
  return local ? new Date(local).toISOString() : undefined;
}

export function MovementLogPage({ token, notify }: { token: string; notify: (m: string) => void }) {
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [skip, setSkip] = useState(0);
  const [page, setPage] = useState<MovementPage | null>(null);
  const [gates, setGates] = useState<Gate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, MovementDetail | "loading">>({});
  const [correcting, setCorrecting] = useState<CorrectionTarget | null>(null);

  useEffect(() => {
    api.gates().then(setGates).catch(() => setGates([]));
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await api.logs(token, {
        plate: filters.plate.trim() || undefined,
        gate_id: filters.gate_id || undefined,
        direction: filters.direction || undefined,
        date_from: toIso(filters.date_from),
        date_to: toIso(filters.date_to),
        linked: filters.linked || undefined,
        skip,
        limit: PAGE_SIZE,
      });
      setPage(res);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the movement log.");
    }
  }, [token, filters, skip]);

  useEffect(() => {
    void load();
  }, [load]);

  const apply = (e: FormEvent) => {
    e.preventDefault();
    setSkip(0);
    setExpanded({});
    setFilters(draft);
  };

  const toggle = async (id: string) => {
    if (expanded[id]) {
      const { [id]: _, ...rest } = expanded;
      setExpanded(rest);
      return;
    }
    setExpanded((x) => ({ ...x, [id]: "loading" }));
    try {
      const detail = await api.logDetail(token, id);
      setExpanded((x) => ({ ...x, [id]: detail }));
    } catch {
      setExpanded((x) => {
        const { [id]: _, ...rest } = x;
        return rest;
      });
    }
  };

  return (
    <div className="space-y-4">
      <form onSubmit={apply} className="grid grid-cols-2 gap-3 rounded-lg bg-white p-3 ring-1 ring-slate-200 md:grid-cols-4 xl:grid-cols-7">
        <Field label="Plate">
          <input className={inputClass + " font-mono uppercase"} value={draft.plate} onChange={(e) => setDraft({ ...draft, plate: e.target.value })} />
        </Field>
        <Field label="Gate">
          <select className={inputClass} value={draft.gate_id} onChange={(e) => setDraft({ ...draft, gate_id: e.target.value })}>
            <option value="">All gates</option>
            {gates.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Movement">
          <select className={inputClass} value={draft.direction} onChange={(e) => setDraft({ ...draft, direction: e.target.value })}>
            <option value="">Both</option>
            <option value="ENTRY">{MOVEMENT_LABEL.ENTRY}</option>
            <option value="EXIT">{MOVEMENT_LABEL.EXIT}</option>
          </select>
        </Field>
        <Field label="From">
          <input type="datetime-local" className={inputClass} value={draft.date_from} onChange={(e) => setDraft({ ...draft, date_from: e.target.value })} />
        </Field>
        <Field label="To">
          <input type="datetime-local" className={inputClass} value={draft.date_to} onChange={(e) => setDraft({ ...draft, date_to: e.target.value })} />
        </Field>
        <Field label="Registry link">
          <select className={inputClass} value={draft.linked} onChange={(e) => setDraft({ ...draft, linked: e.target.value })}>
            <option value="">Any</option>
            <option value="true">Linked</option>
            <option value="false">Not linked</option>
          </select>
        </Field>
        <div className="flex items-end gap-2">
          <button type="submit" className={primaryButton}>
            Apply
          </button>
          <button
            type="button"
            className={secondaryButton}
            onClick={() => {
              setDraft(EMPTY);
              setFilters(EMPTY);
              setSkip(0);
            }}
          >
            Clear
          </button>
        </div>
      </form>

      {error && <p className="text-sm text-slate-700">{error}</p>}

      <div className="overflow-x-auto rounded-lg bg-white ring-1 ring-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Gate</th>
              <th className="px-3 py-2">Movement</th>
              <th className="px-3 py-2">Vehicle</th>
              <th className="px-3 py-2">Context</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {page?.items.map((m) => {
              const detail = expanded[m.id];
              return (
                <Fragment key={m.id}>
                  <tr>
                    <td className="whitespace-nowrap px-3 py-2 text-xs tabular-nums text-slate-700">{formatDateTime(m.timestamp)}</td>
                    <td className="px-3 py-2 text-xs text-slate-700">{m.gate.name}</td>
                    <td className="px-3 py-2 text-xs">
                      <MovementLabel direction={m.direction} method={m.direction_method} corrected={m.corrected} />
                    </td>
                    <td className="px-3 py-2">
                      <SubjectCell plate={m.normalized_plate} vehicle={m.vehicle} owner={m.owner} residence={m.residence} />
                    </td>
                    <td className="px-3 py-2">
                      <FlagChips flags={m.flags} hide={["CORRECTED"]} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-xs">
                      <button type="button" className="mr-3 text-slate-600 underline" onClick={() => void toggle(m.id)}>
                        {detail ? "Hide record" : "Record"}
                      </button>
                      <button
                        type="button"
                        className="mr-3 text-slate-600 underline"
                        onClick={() => setCorrecting({ movementId: m.id, direction: m.direction, plate: m.normalized_plate })}
                      >
                        Correct
                      </button>
                      {(m.vehicle?.plate ?? m.normalized_plate) && (
                        <button type="button" className="text-slate-600 underline" onClick={() => navigate("history", m.vehicle?.plate ?? m.normalized_plate)}>
                          History
                        </button>
                      )}
                    </td>
                  </tr>
                  {detail && (
                    <tr className="bg-slate-50">
                      <td colSpan={6} className="px-3 py-2">
                        {detail === "loading" ? (
                          <span className="text-xs text-slate-500">Loading…</span>
                        ) : (
                          <ol className="space-y-1 text-xs text-slate-700">
                            {detail.rows.map((r, i) => (
                              <li key={r.id}>
                                <span className="font-medium">{i === 0 ? "Original" : `Correction ${i}`}</span> · {formatDateTime(r.created_at)} ·{" "}
                                {MOVEMENT_LABEL[r.direction]} ({METHOD_LABEL[r.direction_method]}) · plate{" "}
                                <span className="font-mono">{r.normalized_plate ?? "none"}</span>
                                {r.plate_source === "GUARD_CORRECTION" ? " (guard)" : ""} · by {r.created_by?.full_name ?? "system"}
                                {r.note ? <> · “{r.note}”</> : null}
                              </li>
                            ))}
                          </ol>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {page && page.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-sm text-slate-500">
                  No movements match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {page && page.total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2 text-xs text-slate-600">
          <span>
            {skip + 1}–{Math.min(skip + PAGE_SIZE, page.total)} of {page.total}
          </span>
          <button type="button" className={secondaryButton + " px-2 py-1 text-xs"} disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}>
            Previous
          </button>
          <button
            type="button"
            className={secondaryButton + " px-2 py-1 text-xs"}
            disabled={skip + PAGE_SIZE >= page.total}
            onClick={() => setSkip(skip + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      )}

      {correcting && (
        <CorrectionModal
          token={token}
          target={correcting}
          onClose={() => setCorrecting(null)}
          onCorrected={() => {
            setCorrecting(null);
            setExpanded({});
            notify("Correction recorded.");
            void load();
          }}
        />
      )}
    </div>
  );
}
