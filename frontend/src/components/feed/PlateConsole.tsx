import { Eye, EyeOff, History, Link2, NotebookPen, UserPlus } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { useHistory } from "../../api/queries";
import type { PersonType, ResolvedObservation } from "../../api/types";
import type { FeedCard } from "../../feed/useLiveFeed";
import { cx } from "../../lib/cx";
import {
  METHOD_LABEL,
  MOVEMENT_LABEL,
  describeOneEdit,
  formatDateTime,
  formatFeedTimestamp,
  formatPercent,
  gateLabel,
  gateShort,
  humanize,
  maskReference,
} from "../../lib/format";
import type { CorrectionTarget } from "../forms/CorrectionDialog";
import type { ManualEntryPrefill } from "../forms/ManualEntryDialog";
import { ReasonCodeBadge, determineReasonCode } from "../ReasonCodeBadge";
import { PlatePill, RegistryStatus } from "../registry/StatusBadges";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Feedback";
import { Field, Input, Select } from "../ui/Form";
import { CandidatesSection, MovementSection, useObservationActions } from "./ObservationCard";
import { SnapshotImage } from "./SnapshotImage";

const COUNT_WORD = ["No", "One", "Two", "Three", "Four", "Five"];
const countWord = (n: number) => COUNT_WORD[n] ?? String(n);

/** Registry candidates one edit away from the read (the slides' "close match"). */
function closeMatches(item: ResolvedObservation) {
  const read = item.observation.plate.normalized ?? "";
  return item.suggestions.filter((s) => describeOneEdit(read, s.plate) !== null);
}

/** ENTERED / LEFT from the logged movement; nothing is guessed. */
function movementTag(item: ResolvedObservation): string | null {
  if (item.movement) return item.movement.direction === "ENTRY" ? "ENTERED" : "LEFT";
  if (item.movement_status === "DIRECTION_UNKNOWN") return "DIRECTION ?";
  return null;
}

/** "Student · SID 2410••••", "Faculty · CSE Department", "Two close matches · read CH01AB124". */
export function ownerLine(item: ResolvedObservation): string {
  const raw = item.observation.plate.raw ?? item.observation.plate.normalized ?? "";
  const o = item.owner;
  if (o) {
    const type = humanize(o.person_type);
    if (o.person_type === "STUDENT") return `${type} · SID ${maskReference(o.institutional_id)}`;
    if (o.person_type === "FACULTY") return `${type} · ID ${maskReference(o.institutional_id)}`;
    if (o.person_type === "RESIDENT") return `${type} · House ${o.institutional_id.toUpperCase()}`;
    return `${type} · ${o.department ?? maskReference(o.institutional_id)}`;
  }
  if (item.vehicle) return `${humanize(item.vehicle.category)} · no owner on record`;
  switch (item.link_status) {
    case "LOW_CONFIDENCE": {
      const n = closeMatches(item).length || item.suggestions.length;
      return n === 0 ? `Uncertain read · read ${raw}` : `${countWord(n)} close match${n === 1 ? "" : "es"} · read ${raw}`;
    }
    case "NOT_LINKED":
      return item.resolution?.outcome === "NONE_OF_THESE" ? `None of the candidates · read ${raw}` : `Not in registry · read ${raw}`;
    case "NO_PLATE":
      return "No plate read";
    default:
      return "—";
  }
}

/** The REGISTRY line of the plate panel, e.g. "Matched CH01AB1234 after removing 1 extra character". */
export function registryExplanation(item: ResolvedObservation): string {
  const read = item.observation.plate.normalized ?? "";
  const v = item.vehicle;
  if (item.link_status === "NO_PLATE") return "No plate was read, so there is nothing to match.";
  if (v) {
    const inactive = item.link_status === "LINKED_INACTIVE" ? " · registration not active" : "";
    if (item.link_basis === "EXACT_PLATE") return `Exact match ${v.plate}${inactive}`;
    const edit = describeOneEdit(read, v.plate);
    const how = edit && edit !== "exact match" ? ` ${edit}` : "";
    return `Matched ${v.plate}${how}, confirmed by ${item.resolution?.created_by.full_name ?? "a guard"}${inactive}`;
  }
  if (item.link_status === "LOW_CONFIDENCE") {
    const close = closeMatches(item);
    if (close.length === 1) return `One close match ${close[0].plate} ${describeOneEdit(read, close[0].plate)} · not applied until a guard confirms`;
    if (close.length > 1) return `${countWord(close.length)} close matches (${close.map((s) => s.plate).join(", ")}) · guard review`;
    if (item.suggestions.length > 0) return `No registry plate within one edit; ${item.suggestions.length} similar plate${item.suggestions.length === 1 ? "" : "s"} below`;
    return "Uncertain read and no registry plate within one edit";
  }
  if (item.resolution?.outcome === "NONE_OF_THESE") return `Guard marked none of the candidates (${item.resolution.created_by.full_name}) · UNLINKED and logged`;
  return "Not in the registry · UNLINKED and logged (unknown is not a threat)";
}

function directionWord(item: ResolvedObservation): string {
  const d = item.movement?.direction ?? (item.direction && item.direction.direction !== "UNKNOWN" ? item.direction.direction : null);
  return d === "ENTRY" ? "entering" : d === "EXIT" ? "leaving" : "direction unknown";
}

/** One row of "Plates read · LIVE". */
export function PlateRow({ card, selected, onSelect }: { card: FeedCard; selected: boolean; onSelect: () => void }) {
  const { item } = card;
  const obs = item.observation;
  const tag = movementTag(item);
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected || undefined}
        className={cx(
          "flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500",
          selected ? "bg-slate-100 dark:bg-slate-800" : "hover:bg-slate-50 dark:hover:bg-slate-800/50",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className={cx("plate text-sm", obs.plate.normalized ? "text-slate-900 dark:text-white" : "text-slate-400")}>{obs.plate.normalized ?? "— — —"}</span>
            {tag && (
              <Badge className="bg-white text-slate-700 ring-slate-300 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-600">{tag}</Badge>
            )}
            <span className="text-[11px] tabular-nums text-slate-500 dark:text-slate-400" title={`${obs.gate.name} · ${formatDateTime(obs.observed_at)}`}>
              {gateShort(obs.gate)} · {formatFeedTimestamp(obs.observed_at, false)}
            </span>
          </div>
          <p className="truncate text-xs text-slate-600 dark:text-slate-400">{ownerLine(item)}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <PlatePill status={item.link_status} />
          <ReasonCodeBadge
            code={determineReasonCode({
              plateConfidence: obs.plate.confidence,
              linkStatus: item.link_status,
              vehicle: item.vehicle,
              flags: item.flags,
            })}
            compact
          />
        </div>
      </button>
    </li>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-slate-900 dark:text-slate-100">{children}</dd>
    </div>
  );
}

const BELONGS_TO: PersonType[] = ["STUDENT", "FACULTY", "STAFF"];

interface PanelProps {
  token: string;
  item: ResolvedObservation;
  onResolved: (item: ResolvedObservation) => void;
  onLink: (plate: string, personType: PersonType, reference: string) => void;
  onMarkVisitor: (plate: string) => void;
  onManualEntry: (prefill: ManualEntryPrefill) => void;
  onCorrect: (target: CorrectionTarget) => void;
}

/** Plate detail: camera frame, OCR read, registry explanation, owner context, link form and audit trail. */
export function PlateDetailPanel({ token, item, onResolved, onLink, onMarkVisitor, onManualEntry, onCorrect }: PanelProps) {
  const obs = item.observation;
  const plate = obs.plate.normalized;
  const { note, setNote, pending, error, resolve, confirmMovement } = useObservationActions(token, item, onResolved);
  const history = useHistory(plate);
  const [revealed, setRevealed] = useState(false);
  const [belongsTo, setBelongsTo] = useState<PersonType>("STUDENT");
  const [reference, setReference] = useState("");
  const manual = obs.source === "MANUAL";
  const o = item.owner;

  const submitLink = (e: FormEvent) => {
    e.preventDefault();
    if (plate) onLink(plate, belongsTo, reference.trim());
  };

  // AUDIT TRAIL: every step from the read to the guard's actions, oldest first.
  const trail: { at: string; text: string }[] = [
    {
      at: obs.observed_at,
      text: manual
        ? `Logged manually at ${gateLabel(obs.gate)} by ${obs.created_by?.full_name ?? "a guard"} (${directionWord(item)})`
        : `Read at ${gateLabel(obs.gate)} (${directionWord(item)})${obs.plate.confidence !== null ? ` · OCR ${formatPercent(obs.plate.confidence)}` : ""}`,
    },
    { at: obs.observed_at, text: `Registry: ${registryExplanation(item)}` },
  ];
  if (!manual && obs.update_count > 0) trail.push({ at: obs.updated_at, text: `Camera refined the read (${obs.update_count} update${obs.update_count === 1 ? "" : "s"})` });
  if (item.resolution)
    trail.push({
      at: item.resolution.created_at,
      text:
        item.resolution.outcome === "VEHICLE_CONFIRMED"
          ? `${item.resolution.created_by.full_name} confirmed ${item.vehicle?.plate ?? "a registry vehicle"}`
          : `${item.resolution.created_by.full_name} marked “none of these”`,
    });
  if (item.movement)
    trail.push({
      at: item.movement.timestamp,
      text: `${MOVEMENT_LABEL[item.movement.direction]} logged (${METHOD_LABEL[item.movement.method]})${item.movement.created_by ? ` by ${item.movement.created_by.full_name}` : ""}${item.movement.corrected ? " · corrected" : ""}`,
    });
  for (const ev of history.data?.link_events ?? [])
    trail.push({ at: ev.linked_at, text: `Linked to an owner by ${ev.linked_by.full_name} (${humanize(ev.method)})${ev.expires_at ? ` until ${formatDateTime(ev.expires_at)}` : ""}` });
  trail.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

  return (
    <div className="space-y-4">
      <div className="relative">
        <SnapshotImage token={token} observation={obs} className="h-52 w-full sm:h-64" />
        <span className="pointer-events-none absolute left-2 top-2 rounded-md bg-slate-950/70 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-white">
          {gateLabel(obs.gate)} · {manual ? "manual" : (obs.camera_id ?? "camera")}
        </span>
        {obs.plate.raw && (
          <span className="pointer-events-none absolute bottom-2 left-2 rounded-md bg-white/90 px-2 py-0.5 font-mono text-xs font-semibold text-slate-900 ring-2 ring-amber-400">
            {obs.plate.raw}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {plate ? (
          <Link to={`/vehicles/${encodeURIComponent(plate)}`} className="plate text-2xl text-slate-900 underline-offset-4 hover:underline dark:text-white">
            {plate}
          </Link>
        ) : (
          <span className="plate text-2xl text-slate-400">— — —</span>
        )}
        <PlatePill status={item.link_status} />
        <ReasonCodeBadge
          code={determineReasonCode({
            plateConfidence: obs.plate.confidence,
            linkStatus: item.link_status,
            vehicle: item.vehicle,
            flags: item.flags,
          })}
        />
        {item.vehicle && <RegistryStatus status={item.vehicle.registry_status} prefix />}
      </div>

      <dl className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
        <Fact label="Observed At">
          <span className="font-medium text-slate-800 dark:text-slate-200">{formatDateTime(obs.observed_at)}</span>
        </Fact>
        <Fact label="OCR read">
          <span className="font-mono">{obs.plate.raw ?? "—"}</span>
          <span className="text-xs text-slate-500 dark:text-slate-400"> · {manual ? "typed by guard" : `confidence ${formatPercent(obs.plate.confidence)}`}</span>
        </Fact>
        <Fact label="Registry">{registryExplanation(item)}</Fact>
        {o && (
          <>
            <Fact label="Owner">
              {humanize(o.person_type)}
              <span className="text-xs text-slate-500 dark:text-slate-400"> · {o.name}</span>
            </Fact>
            <Fact label="Reference">
              <span className="font-mono">
                {o.person_type === "STUDENT" ? "SID " : o.person_type === "FACULTY" ? "Faculty ID " : o.person_type === "RESIDENT" ? "House " : ""}
                {revealed ? o.institutional_id : maskReference(o.institutional_id)}
              </span>
              <button type="button" className="ml-2 inline-flex items-center gap-1 align-middle text-xs text-slate-500 hover:text-slate-900 dark:hover:text-white" onClick={() => setRevealed((r) => !r)}>
                {revealed ? <EyeOff className="h-3 w-3" aria-hidden /> : <Eye className="h-3 w-3" aria-hidden />}
                {revealed ? "Hide" : "Show"}
              </button>
              {o.department && <span className="block text-xs text-slate-500 dark:text-slate-400">{o.department}</span>}
            </Fact>
            <Fact label="Residence">
              {humanize(item.residence?.residence_type)}
              {item.residence?.residence ? `, ${item.residence.residence}` : ""}
              <span className="block text-xs text-slate-500 dark:text-slate-400">Kept on the owner, not the vehicle</span>
            </Fact>
          </>
        )}
        {item.vehicle && (
          <Fact label="Vehicle">
            {humanize(item.vehicle.category)}
            {[item.vehicle.color, item.vehicle.make_model].filter(Boolean).length > 0 && (
              <span className="text-xs text-slate-500 dark:text-slate-400"> · {[item.vehicle.color, item.vehicle.make_model].filter(Boolean).join(" ")}</span>
            )}
          </Fact>
        )}
      </dl>

      <section className="border-t border-slate-100 pt-3 dark:border-slate-800" aria-label="Movement">
        <MovementSection item={item} pending={pending} onConfirm={(d) => void confirmMovement(d)} onCorrect={onCorrect} />
      </section>

      <CandidatesSection item={item} note={note} setNote={setNote} pending={pending} onResolve={(c) => void resolve(c)} />
      {error && <p className="text-xs font-medium text-slate-800 dark:text-slate-200">{error}</p>}

      {plate && !item.vehicle && (
        <section className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200 dark:bg-slate-800/50 dark:ring-slate-700" aria-label="Link this vehicle">
          <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Link this vehicle</h3>
          <form onSubmit={submitLink} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Belongs to">
                <Select value={belongsTo} onChange={(e) => setBelongsTo(e.target.value as PersonType)}>
                  {BELONGS_TO.map((p) => (
                    <option key={p} value={p}>
                      {humanize(p)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={belongsTo === "STUDENT" ? "SID" : "Employee ID or department"}>
                <Input
                  className="font-mono"
                  placeholder={belongsTo === "STUDENT" ? "e.g. 2410xxxx" : "e.g. EMP-1042 or CSE Department"}
                  maxLength={100}
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  autoComplete="off"
                />
              </Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" size="sm" variant="primary" icon={<Link2 className="h-3.5 w-3.5" />}>
                Link vehicle
              </Button>
              <Button size="sm" icon={<UserPlus className="h-3.5 w-3.5" />} onClick={() => onMarkVisitor(plate)}>
                Mark as visitor
              </Button>
            </div>
            <p className="hint">You confirm the ID shown by the driver; the link is recorded under your name and earlier sightings of this plate pick it up.</p>
          </form>
        </section>
      )}

      <section aria-label="Audit trail">
        <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Audit trail</h3>
        <ol className="space-y-1">
          {trail.map((t, i) => (
            <li key={i} className="flex gap-3 text-xs">
              <span className="shrink-0 tabular-nums text-slate-500 dark:text-slate-400" title={formatDateTime(t.at)}>
                {formatFeedTimestamp(t.at, true)}
              </span>
              <span className="min-w-0 text-slate-700 dark:text-slate-300">{t.text}</span>
            </li>
          ))}
        </ol>
      </section>

      <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
        {plate && (
          <Link to={`/vehicles/${encodeURIComponent(plate)}`} className="btn btn-ghost btn-sm">
            <History className="h-3.5 w-3.5" aria-hidden />
            Full history
          </Link>
        )}
        <Button size="sm" variant="ghost" icon={<NotebookPen className="h-3.5 w-3.5" />} onClick={() => onManualEntry({ plate: plate ?? undefined, gateId: obs.gate.id })}>
          Manual entry
        </Button>
      </div>
    </div>
  );
}
