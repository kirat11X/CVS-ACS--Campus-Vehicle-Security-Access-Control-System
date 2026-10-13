import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { MovementDirection, ResolvedObservation, RegistrySuggestion } from "../api/types";
import type { FeedCard } from "../feed/useLiveFeed";
import {
  DIRECTION_REASON,
  LINK_STATUS_HINT,
  LINK_STATUS_LABEL,
  LINK_STATUS_STYLE,
  formatDateTime,
  formatPercent,
  formatTime,
  humanize,
  METHOD_LABEL,
  MOVEMENT_LABEL,
} from "../lib/format";
import { navigate } from "../lib/route";
import { SnapshotImage } from "./SnapshotImage";
import { inputClass, secondaryButton } from "./Modal";
import { MovementLabel } from "./movement/MovementLabel";
import type { CorrectionTarget } from "./movement/CorrectionModal";

export interface ManualEntryPrefill {
  plate?: string;
  gateId?: string;
}

interface Props {
  token: string;
  card: FeedCard;
  onRegister: (plate: string) => void;
  onManualEntry: (prefill: ManualEntryPrefill) => void;
  onResolved: (item: ResolvedObservation) => void;
  onLink: (plate: string) => void;
  onCorrect: (target: CorrectionTarget) => void;
}

const UPDATE_HIGHLIGHT_MS = 4000;

function RegistryStatus({ status }: { status: string }) {
  // Shown exactly as recorded in the registry. BLACKLISTED is an existing registry
  // status set by an administrator, so it is visually distinct; nothing else is.
  const tone = status === "BLACKLISTED" ? "bg-rose-50 text-rose-900 ring-rose-300" : "bg-slate-50 text-slate-700 ring-slate-300";
  return (
    <span className={`inline-flex rounded px-1.5 py-0.5 font-mono text-[11px] ring-1 ${tone}`}>Registry status: {status}</span>
  );
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="truncate text-sm text-slate-900">{value || "—"}</dd>
    </div>
  );
}

function MovementSection({
  item,
  pending,
  onConfirm,
  onCorrect,
}: {
  item: ResolvedObservation;
  pending: string | null;
  onConfirm: (d: MovementDirection) => void;
  onCorrect: (target: CorrectionTarget) => void;
}) {
  if (item.movement) {
    const m = item.movement;
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <MovementLabel direction={m.direction} method={m.method} corrected={m.corrected} />
        {m.created_by && <span className="text-xs text-slate-500">by {m.created_by.full_name}</span>}
        <button
          type="button"
          className="ml-auto text-xs text-slate-600 underline hover:text-slate-900"
          onClick={() => onCorrect({ movementId: m.id, direction: m.direction, plate: m.normalized_plate })}
        >
          Correct
        </button>
      </div>
    );
  }
  const d = item.direction;
  if (item.movement_status === "REPEAT_NOT_LOGGED" && d && d.direction !== "UNKNOWN") {
    return (
      <p className="text-sm text-slate-600">
        {MOVEMENT_LABEL[d.direction]} · {METHOD_LABEL[d.method]}{" "}
        <span className="text-xs text-slate-500">(repeat of a recent movement at this gate; not logged separately)</span>
      </p>
    );
  }
  const reason = typeof d?.evidence?.reason === "string" ? DIRECTION_REASON[d.evidence.reason as string] : undefined;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="font-medium text-slate-700">Direction unknown</span>
      {reason && <span className="text-xs text-slate-500">({reason})</span>}
      <span className="ml-auto flex gap-2">
        {(["ENTRY", "EXIT"] as MovementDirection[]).map((dir) => (
          <button
            key={dir}
            type="button"
            className={secondaryButton + " px-2 py-1 text-xs"}
            disabled={pending !== null}
            onClick={() => onConfirm(dir)}
          >
            {pending === dir ? "Saving…" : dir === "ENTRY" ? "Confirm entry" : "Confirm exit"}
          </button>
        ))}
      </span>
    </div>
  );
}

export function ObservationCard({ token, card, onRegister, onManualEntry, onResolved, onLink, onCorrect }: Props) {
  const { item, kind, receivedAt } = card;
  const obs = item.observation;
  const style = LINK_STATUS_STYLE[item.link_status];
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recentlyUpdated, setRecentlyUpdated] = useState(false);
  const plate = obs.plate.normalized;

  useEffect(() => {
    if (kind === "SNAPSHOT" || kind === "OBSERVATION_CREATED") return;
    setRecentlyUpdated(true);
    const timer = window.setTimeout(() => setRecentlyUpdated(false), UPDATE_HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [kind, receivedAt]);

  const resolve = async (chosen: RegistrySuggestion | "none") => {
    const key = chosen === "none" ? "none" : chosen.vehicle_id;
    setPending(key);
    setError(null);
    try {
      const res = await api.recordResolution(token, {
        observation_id: obs.id,
        chosen_vehicle_id: key,
        note: note.trim() || null,
      });
      setNote("");
      onResolved(res.item);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record the confirmation.");
    } finally {
      setPending(null);
    }
  };

  const confirmMovement = async (direction: MovementDirection) => {
    setPending(direction);
    setError(null);
    try {
      await api.confirmMovement(token, { observation_id: obs.id, direction });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record the movement.");
    } finally {
      setPending(null);
    }
  };

  return (
    <article
      className={`rounded-lg border-l-4 bg-white p-4 shadow-sm ring-1 transition-shadow ${style.edge} ${
        recentlyUpdated ? "ring-2 ring-sky-300" : "ring-slate-200"
      }`}
      aria-label={`Observation ${plate ?? "without plate"} at ${obs.gate.name}`}
    >
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${style.badge}`} title={LINK_STATUS_HINT[item.link_status]}>
          {LINK_STATUS_LABEL[item.link_status]}
        </span>
        <span className="text-xs text-slate-600">
          {obs.gate.name} <span className="text-slate-400">({obs.gate.id})</span>
        </span>
        <span className="text-xs text-slate-500" title={formatDateTime(obs.observed_at)}>
          {formatTime(obs.observed_at)}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
          {obs.source === "MANUAL" ? "Manual entry" : obs.source === "FRIGATE" ? `Camera ${obs.camera_id ?? ""}` : humanize(obs.source)}
        </span>
        {recentlyUpdated && <span className="text-[11px] font-medium text-sky-700">Updated</span>}
      </header>

      <div className="flex flex-col gap-4 sm:flex-row">
        <SnapshotImage token={token} observation={obs} />
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <div className="font-mono text-2xl font-semibold tracking-wider text-slate-900">{plate ?? "— — —"}</div>
            <div className="text-xs text-slate-500">
              {obs.plate.raw ? (
                <>
                  Read as <span className="font-mono text-slate-700">“{obs.plate.raw}”</span> ·{" "}
                </>
              ) : null}
              Plate confidence {obs.source === "MANUAL" ? "n/a (typed by guard)" : formatPercent(obs.plate.confidence)}
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            <Detail
              label={obs.source === "MANUAL" ? "Direction (guard)" : "Sensor direction"}
              value={obs.direction === "UNKNOWN" ? "Unknown" : humanize(obs.direction)}
            />
            <Detail
              label="Vehicle type"
              value={`${humanize(obs.vehicle_observation.type)}${
                obs.vehicle_observation.confidence !== null ? ` · ${formatPercent(obs.vehicle_observation.confidence)}` : ""
              }`}
            />
            <Detail label="Frigate updates" value={obs.source === "FRIGATE" ? String(obs.update_count) : null} />
          </dl>
          {obs.source === "MANUAL" && (
            <p className="text-xs text-slate-600">
              Logged by {obs.created_by?.full_name ?? "unknown"}
              {obs.note ? <>: “{obs.note}”</> : null}
            </p>
          )}
        </div>
      </div>

      <section className="mt-3 border-t border-slate-100 pt-3" aria-label="Movement">
        <MovementSection item={item} pending={pending} onConfirm={confirmMovement} onCorrect={onCorrect} />
      </section>

      {item.vehicle && (
        <section className="mt-3 rounded-md bg-slate-50 p-3 ring-1 ring-slate-200">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-slate-900">{item.vehicle.plate}</span>
            <span className="text-xs text-slate-600">{humanize(item.vehicle.category)}</span>
            <RegistryStatus status={item.vehicle.registry_status} />
            <span className="text-[11px] text-slate-500">
              {item.link_basis === "GUARD_CONFIRMED" ? "Confirmed by guard" : "Exact plate match"}
            </span>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
            <Detail label="Owner" value={item.owner?.name} />
            <Detail label="ID" value={item.owner?.institutional_id} />
            <Detail label="Person" value={humanize(item.residence?.person_type)} />
            <Detail label="Residence" value={humanize(item.residence?.residence_type)} />
            <Detail label="Block / address" value={item.residence?.residence} />
            <Detail label="Vehicle" value={[item.vehicle.color, item.vehicle.make_model].filter(Boolean).join(" ") || null} />
          </dl>
          {(item.vehicle.valid_from || item.vehicle.valid_until) && (
            <p className="mt-2 text-xs text-slate-600">
              Validity {item.vehicle.valid_from ? formatDateTime(item.vehicle.valid_from) : "—"} →{" "}
              {item.vehicle.valid_until ? formatDateTime(item.vehicle.valid_until) : "—"}
              {item.flags.includes("VALIDITY_ENDED") && <span className="ml-1 font-medium">(window has ended)</span>}
              {item.flags.includes("VALIDITY_NOT_STARTED") && <span className="ml-1 font-medium">(window not started)</span>}
            </p>
          )}
        </section>
      )}

      {item.resolution && (
        <p className="mt-3 text-xs text-slate-600">
          {item.resolution.outcome === "VEHICLE_CONFIRMED" ? "Vehicle confirmed" : "Marked “none of these”"} by{" "}
          {item.resolution.created_by.full_name} at {formatTime(item.resolution.created_at)}
          {item.resolution.note ? <> · “{item.resolution.note}”</> : null}
        </p>
      )}

      {item.suggestions.length > 0 && (
        <section className="mt-3">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Registry candidates (not applied)</h3>
          <ul className="divide-y divide-slate-100 rounded-md ring-1 ring-slate-200">
            {item.suggestions.map((s) => {
              const chosen = item.resolution?.chosen_vehicle_id === s.vehicle_id;
              return (
                <li key={s.vehicle_id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                  <span className="font-mono text-sm font-semibold text-slate-900">{s.plate}</span>
                  <span className="text-xs text-slate-600">{s.owner_name ?? "No owner on record"}</span>
                  <span className="text-xs text-slate-500">{humanize(s.category)}</span>
                  <RegistryStatus status={s.registry_status} />
                  <span className="ml-auto text-xs tabular-nums text-slate-600">{formatPercent(s.similarity)} similar</span>
                  <button
                    type="button"
                    className={secondaryButton + " px-2 py-1 text-xs"}
                    disabled={pending !== null || chosen}
                    onClick={() => resolve(s)}
                  >
                    {chosen ? "Confirmed" : pending === s.vehicle_id ? "Saving…" : "Confirm"}
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              className={inputClass + " flex-1 py-1 text-xs"}
              placeholder="Note for the confirmation (optional)"
              value={note}
              maxLength={1000}
              onChange={(e) => setNote(e.target.value)}
            />
            <button
              type="button"
              className={secondaryButton + " px-2 py-1 text-xs"}
              disabled={pending !== null || item.resolution?.outcome === "NONE_OF_THESE"}
              onClick={() => resolve("none")}
            >
              {pending === "none" ? "Saving…" : "None of these"}
            </button>
          </div>
        </section>
      )}

      {error && <p className="mt-2 text-xs text-slate-800">{error}</p>}

      <footer className="mt-3 flex flex-wrap gap-2">
        {plate && !item.vehicle && (
          <>
            <button type="button" className={secondaryButton + " text-xs"} onClick={() => onLink(plate)}>
              Link to owner
            </button>
            <button type="button" className={secondaryButton + " text-xs"} onClick={() => onRegister(plate)}>
              Register vehicle
            </button>
          </>
        )}
        {plate && (
          <button type="button" className={secondaryButton + " text-xs"} onClick={() => navigate("history", plate)}>
            History
          </button>
        )}
        <button
          type="button"
          className={secondaryButton + " text-xs"}
          onClick={() => onManualEntry({ plate: plate ?? undefined, gateId: obs.gate.id })}
        >
          Log manual entry
        </button>
      </footer>
    </article>
  );
}
