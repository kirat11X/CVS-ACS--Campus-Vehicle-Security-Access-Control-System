import { ArrowLeftFromLine, ArrowRightToLine, History, Keyboard, Link2, NotebookPen, PlusCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError, api } from "../../api/client";
import { MOVEMENT_ROOTS, useInvalidate } from "../../api/queries";
import type { MovementDirection, RegistrySuggestion, ResolvedObservation } from "../../api/types";
import type { FeedCard } from "../../feed/useLiveFeed";
import { cx } from "../../lib/cx";
import { DIRECTION_REASON, LINK_STATUS_STYLE, METHOD_LABEL, MOVEMENT_LABEL, formatDateTime, formatPercent, formatTime, humanize } from "../../lib/format";
import type { CorrectionTarget } from "../forms/CorrectionDialog";
import type { ManualEntryPrefill } from "../forms/ManualEntryDialog";
import { MovementLabel } from "../movement/MovementLabel";
import { ReasonCodeBadge, determineReasonCode } from "../ReasonCodeBadge";
import { LinkStatusBadge, RegistryStatus } from "../registry/StatusBadges";
import { Button } from "../ui/Button";
import { Input } from "../ui/Form";
import { SnapshotImage } from "./SnapshotImage";

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

function Fact({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="truncate text-xs text-slate-800 dark:text-slate-200">{value || "—"}</dd>
    </div>
  );
}

/** Guard actions on one sighting (confirm a registry candidate, confirm a direction), shared by the card and the detail panel. */
export function useObservationActions(token: string, item: ResolvedObservation, onResolved: (item: ResolvedObservation) => void) {
  const invalidate = useInvalidate();
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const obsId = item.observation.id;

  const resolve = async (chosen: RegistrySuggestion | "none") => {
    const key = chosen === "none" ? "none" : chosen.vehicle_id;
    setPending(key);
    setError(null);
    try {
      const res = await api.recordResolution(token, { observation_id: obsId, chosen_vehicle_id: key, note: note.trim() || null });
      setNote("");
      onResolved(res.item);
      void invalidate("dashboard", "history", "alerts");
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
      await api.confirmMovement(token, { observation_id: obsId, direction });
      void invalidate(...MOVEMENT_ROOTS);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record the movement.");
    } finally {
      setPending(null);
    }
  };

  return { note, setNote, pending, error, resolve, confirmMovement };
}

/** Fuzzy registry candidates; never applied until a guard confirms one. */
export function CandidatesSection({
  item,
  note,
  setNote,
  pending,
  onResolve,
}: {
  item: ResolvedObservation;
  note: string;
  setNote: (v: string) => void;
  pending: string | null;
  onResolve: (chosen: RegistrySuggestion | "none") => void;
}) {
  if (item.suggestions.length === 0) return null;
  return (
    <section className="mt-3">
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Registry candidates (not applied)</h3>
      <ul className="divide-y divide-slate-100 rounded-lg ring-1 ring-slate-200 dark:divide-slate-800 dark:ring-slate-700">
        {item.suggestions.map((s) => {
          const chosen = item.resolution?.chosen_vehicle_id === s.vehicle_id;
          return (
            <li key={s.vehicle_id} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
              <span className="plate text-sm text-slate-900 dark:text-white">{s.plate}</span>
              <span className="text-xs text-slate-600 dark:text-slate-400">{s.owner_name ?? "No owner on record"}</span>
              <span className="text-xs text-slate-500">{humanize(s.category)}</span>
              <RegistryStatus status={s.registry_status} />
              <span className="ml-auto text-xs tabular-nums text-slate-600 dark:text-slate-400">{formatPercent(s.similarity)} similar</span>
              <Button size="sm" disabled={pending !== null || chosen} loading={pending === s.vehicle_id} onClick={() => onResolve(s)}>
                {chosen ? "Confirmed" : "Confirm"}
              </Button>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <Input
          className="py-1.5 text-sm sm:text-xs"
          placeholder="Note for the confirmation (optional)"
          value={note}
          maxLength={1000}
          onChange={(e) => setNote(e.target.value)}
          aria-label="Confirmation note"
        />
        <Button
          size="sm"
          className="shrink-0"
          disabled={pending !== null || item.resolution?.outcome === "NONE_OF_THESE"}
          loading={pending === "none"}
          onClick={() => onResolve("none")}
        >
          None of these
        </Button>
      </div>
    </section>
  );
}

export function MovementSection({
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
        {m.created_by && <span className="text-xs text-slate-500 dark:text-slate-400">by {m.created_by.full_name}</span>}
        <button
          type="button"
          className="ml-auto text-xs font-medium text-slate-600 underline-offset-2 hover:underline dark:text-slate-300"
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
      <p className="text-sm text-slate-600 dark:text-slate-400">
        {MOVEMENT_LABEL[d.direction]} · {METHOD_LABEL[d.method]}{" "}
        <span className="text-xs text-slate-500">(repeat of a recent movement at this gate; not logged separately)</span>
      </p>
    );
  }
  const reason = typeof d?.evidence?.reason === "string" ? DIRECTION_REASON[d.evidence.reason as string] : undefined;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <div className="mr-auto min-w-0">
        <span className="font-medium text-slate-800 dark:text-slate-200">Direction unknown</span>
        {reason && <span className="block text-xs text-slate-500 dark:text-slate-400">{reason}</span>}
      </div>
      <div className="flex gap-2">
        {(["ENTRY", "EXIT"] as MovementDirection[]).map((dir) => (
          <Button
            key={dir}
            size="sm"
            loading={pending === dir}
            disabled={pending !== null}
            onClick={() => onConfirm(dir)}
            icon={dir === "ENTRY" ? <ArrowRightToLine className="h-3.5 w-3.5" /> : <ArrowLeftFromLine className="h-3.5 w-3.5" />}
          >
            {dir === "ENTRY" ? "Confirm entry" : "Confirm exit"}
          </Button>
        ))}
      </div>
    </div>
  );
}

export function ObservationCard({ token, card, onRegister, onManualEntry, onResolved, onLink, onCorrect }: Props) {
  const { item, kind, receivedAt } = card;
  const obs = item.observation;
  const style = LINK_STATUS_STYLE[item.link_status];
  const { note, setNote, pending, error, resolve, confirmMovement } = useObservationActions(token, item, onResolved);
  const [recentlyUpdated, setRecentlyUpdated] = useState(false);
  const plate = obs.plate.normalized;

  useEffect(() => {
    if (kind === "SNAPSHOT" || kind === "OBSERVATION_CREATED") return;
    setRecentlyUpdated(true);
    const timer = window.setTimeout(() => setRecentlyUpdated(false), UPDATE_HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [kind, receivedAt]);

  const source = obs.source === "MANUAL" ? "Manual entry" : obs.source === "FRIGATE" ? `Camera ${obs.camera_id ?? ""}` : humanize(obs.source);

  return (
    <article
      className={cx(
        "card overflow-hidden border-l-4 transition-shadow",
        style.edge,
        recentlyUpdated && "ring-2 ring-sky-300 dark:ring-sky-500/60",
      )}
      aria-label={`Observation ${plate ?? "without plate"} at ${obs.gate.name}`}
    >
      <div className="p-4">
        <header className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1">
          <LinkStatusBadge status={item.link_status} />
          <ReasonCodeBadge
            code={determineReasonCode({
              plateConfidence: obs.plate.confidence,
              linkStatus: item.link_status,
              vehicle: item.vehicle,
              flags: item.flags,
            })}
            compact
          />
          <span className="text-xs text-slate-600 dark:text-slate-300">{obs.gate.name}</span>
          <span className="text-xs tabular-nums text-slate-500 dark:text-slate-400" title={formatDateTime(obs.observed_at)}>
            {formatTime(obs.observed_at)}
          </span>
          <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-400">
            {obs.source === "MANUAL" && <Keyboard className="h-3 w-3" aria-hidden />}
            {source}
          </span>
          {recentlyUpdated && <span className="text-[11px] font-semibold text-sky-700 dark:text-sky-400">Updated</span>}
        </header>

        <div className="flex gap-3 sm:gap-4">
          <SnapshotImage token={token} observation={obs} />
          <div className="min-w-0 flex-1 space-y-2">
            <div>
              {plate ? (
                <Link to={`/vehicles/${encodeURIComponent(plate)}`} className="plate text-xl text-slate-900 underline-offset-4 hover:underline dark:text-white sm:text-2xl">
                  {plate}
                </Link>
              ) : (
                <span className="plate text-xl text-slate-400 sm:text-2xl">— — —</span>
              )}
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {obs.plate.raw ? (
                  <>
                    Read as <span className="font-mono text-slate-700 dark:text-slate-300">“{obs.plate.raw}”</span> ·{" "}
                  </>
                ) : null}
                {obs.source === "MANUAL" ? "typed by guard" : `confidence ${formatPercent(obs.plate.confidence)}`}
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-3">
              <Fact label={obs.source === "MANUAL" ? "Direction (guard)" : "Sensor direction"} value={obs.direction === "UNKNOWN" ? "Unknown" : humanize(obs.direction)} />
              <Fact
                label="Vehicle type"
                value={`${humanize(obs.vehicle_observation.type)}${obs.vehicle_observation.confidence !== null ? ` · ${formatPercent(obs.vehicle_observation.confidence)}` : ""}`}
              />
              {obs.source === "FRIGATE" && <Fact label="Frigate updates" value={String(obs.update_count)} />}
            </dl>
            {obs.source === "MANUAL" && (
              <p className="text-xs text-slate-600 dark:text-slate-400">
                Logged by {obs.created_by?.full_name ?? "unknown"}
                {obs.note ? <>: “{obs.note}”</> : null}
              </p>
            )}
          </div>
        </div>

        <section className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800" aria-label="Movement">
          <MovementSection item={item} pending={pending} onConfirm={(d) => void confirmMovement(d)} onCorrect={onCorrect} />
        </section>

        {item.vehicle && (
          <section className="mt-3 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 dark:bg-slate-800/50 dark:ring-slate-700">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="plate text-sm text-slate-900 dark:text-white">{item.vehicle.plate}</span>
              <span className="text-xs text-slate-600 dark:text-slate-400">{humanize(item.vehicle.category)}</span>
              <RegistryStatus status={item.vehicle.registry_status} prefix />
              <span className="text-[11px] text-slate-500 dark:text-slate-400">{item.link_basis === "GUARD_CONFIRMED" ? "Confirmed by guard" : "Exact plate match"}</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 sm:grid-cols-3">
              <Fact label="Owner" value={item.owner?.name} />
              <Fact label="ID" value={item.owner?.institutional_id} />
              <Fact label="Person" value={humanize(item.residence?.person_type)} />
              <Fact label="Residence" value={humanize(item.residence?.residence_type)} />
              <Fact label="Block / address" value={item.residence?.residence} />
              <Fact label="Vehicle" value={[item.vehicle.color, item.vehicle.make_model].filter(Boolean).join(" ") || null} />
            </dl>
            {(item.vehicle.valid_from || item.vehicle.valid_until) && (
              <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">
                Validity {item.vehicle.valid_from ? formatDateTime(item.vehicle.valid_from) : "—"} → {item.vehicle.valid_until ? formatDateTime(item.vehicle.valid_until) : "—"}
                {item.flags.includes("VALIDITY_ENDED") && <span className="ml-1 font-semibold">(window has ended)</span>}
                {item.flags.includes("VALIDITY_NOT_STARTED") && <span className="ml-1 font-semibold">(window not started)</span>}
              </p>
            )}
          </section>
        )}

        {item.resolution && (
          <p className="mt-3 text-xs text-slate-600 dark:text-slate-400">
            {item.resolution.outcome === "VEHICLE_CONFIRMED" ? "Vehicle confirmed" : "Marked “none of these”"} by {item.resolution.created_by.full_name} at{" "}
            {formatTime(item.resolution.created_at)}
            {item.resolution.note ? <> · “{item.resolution.note}”</> : null}
          </p>
        )}

        <CandidatesSection item={item} note={note} setNote={setNote} pending={pending} onResolve={(c) => void resolve(c)} />

        {error && <p className="mt-2 text-xs font-medium text-slate-800 dark:text-slate-200">{error}</p>}
      </div>

      <footer className="flex flex-wrap gap-2 border-t border-slate-100 bg-slate-50/60 px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900/40">
        {plate && !item.vehicle && (
          <>
            <Button size="sm" icon={<Link2 className="h-3.5 w-3.5" />} onClick={() => onLink(plate)}>
              Link to owner
            </Button>
            <Button size="sm" icon={<PlusCircle className="h-3.5 w-3.5" />} onClick={() => onRegister(plate)}>
              Register
            </Button>
          </>
        )}
        {plate && (
          <Link to={`/vehicles/${encodeURIComponent(plate)}`} className="btn btn-ghost btn-sm">
            <History className="h-3.5 w-3.5" aria-hidden />
            History
          </Link>
        )}
        <Button size="sm" variant="ghost" icon={<NotebookPen className="h-3.5 w-3.5" />} onClick={() => onManualEntry({ plate: plate ?? undefined, gateId: obs.gate.id })}>
          Manual entry
        </Button>
      </footer>
    </article>
  );
}
