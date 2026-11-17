import { ArrowLeftFromLine, ArrowRightToLine, Ban, Eye, Link2, Pencil, Plus, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import { REGISTRY_ROOTS, useHistory, useInvalidate, useVehicle } from "../api/queries";
import type { TimelineItem } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { normalizePlate } from "../app/nav";
import { CorrectionDialog, type CorrectionTarget } from "../components/forms/CorrectionDialog";
import { LinkOwnerDialog } from "../components/forms/LinkOwnerDialog";
import { RegisterVehicleDialog } from "../components/forms/RegisterVehicleDialog";
import { VehicleEditDialog } from "../components/forms/VehicleEditDialog";
import { FlagChips } from "../components/movement/FlagChips";
import { MovementLabel } from "../components/movement/MovementLabel";
import { LinkStatusBadge, RegistryStatus } from "../components/registry/StatusBadges";
import { ReasonCodeBadge, determineReasonCode } from "../components/ReasonCodeBadge";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/Feedback";
import { SearchInput } from "../components/ui/Form";
import { Detail, DetailList, PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { DIRECTION_REASON, METHOD_LABEL, MOVEMENT_LABEL, PRESENCE_LABEL, formatDateTime, formatPercent, humanize } from "../lib/format";

function Lookup() {
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const plate = normalizePlate(value);
    if (plate) navigate(`/vehicles/${encodeURIComponent(plate)}`);
  };
  return (
    <form onSubmit={submit} className="flex max-w-md gap-2" role="search">
      <SearchInput label="Plate" placeholder="Plate, e.g. PB65AB1234" value={value} onChange={setValue} className="flex-1" mono autoFocus />
      <Button type="submit" variant="primary" icon={<Search className="h-4 w-4" />}>
        Look up
      </Button>
    </form>
  );
}

function TimelineRow({ t, onCorrect }: { t: TimelineItem; onCorrect: (target: CorrectionTarget) => void }) {
  const icon =
    t.movement?.direction === "ENTRY" ? (
      <ArrowRightToLine className="h-3.5 w-3.5" />
    ) : t.movement?.direction === "EXIT" ? (
      <ArrowLeftFromLine className="h-3.5 w-3.5" />
    ) : (
      <Eye className="h-3.5 w-3.5" />
    );
  return (
    <li className="relative flex gap-3 pb-5 pl-1 last:pb-0">
      <span className="absolute left-[15px] top-8 h-[calc(100%-2rem)] w-px bg-slate-200 dark:bg-slate-800" aria-hidden />
      <span
        className={cx(
          "relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-4 ring-white dark:ring-slate-900",
          t.movement ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
        )}
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {t.movement ? (
            <>
              <MovementLabel direction={t.movement.direction} method={t.movement.direction_method} corrected={t.movement.corrected} />
              <ReasonCodeBadge
                code={determineReasonCode({
                  plateConfidence: t.movement.direction_confidence,
                  linkStatus: t.movement.linked ? "LINKED" : "NOT_LINKED",
                  vehicle: t.movement.vehicle,
                  flags: t.movement.flags,
                })}
                compact
              />
            </>
          ) : t.sighting ? (
            <>
              <span className="text-slate-700 dark:text-slate-300">
                Seen
                {t.sighting.direction && t.sighting.direction.direction !== "UNKNOWN"
                  ? ` · ${MOVEMENT_LABEL[t.sighting.direction.direction]} (${METHOD_LABEL[t.sighting.direction.method]}), repeat not logged`
                  : ` · direction unknown${
                      typeof t.sighting.direction?.evidence?.reason === "string"
                        ? ` (${DIRECTION_REASON[t.sighting.direction.evidence.reason as string] ?? "no declared source"})`
                        : ""
                    }`}
              </span>
              <ReasonCodeBadge
                code={determineReasonCode({
                  plateConfidence: t.sighting.observation.plate.confidence,
                  linkStatus: t.sighting.link_status,
                  vehicle: t.sighting.vehicle,
                  flags: t.sighting.flags,
                })}
                compact
              />
            </>
          ) : null}
          {t.sighting && <LinkStatusBadge status={t.sighting.link_status} short />}
          {t.movement && (
            <button
              type="button"
              className="ml-auto text-xs font-medium text-slate-600 underline-offset-2 hover:underline dark:text-slate-300"
              onClick={() => onCorrect({ movementId: t.movement!.id, direction: t.movement!.direction, plate: t.movement!.normalized_plate })}
            >
              Correct
            </button>
          )}
        </div>
        <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
          {formatDateTime(t.time)} · {t.gate.name}
          {t.sighting && t.sighting.observation.source !== "MANUAL" && ` · plate confidence ${formatPercent(t.sighting.observation.plate.confidence)}`}
          {t.sighting?.observation.source === "MANUAL" && ` · manual entry by ${t.sighting.observation.created_by?.full_name ?? "a guard"}`}
          {t.movement?.recorded_by && ` · by ${t.movement.recorded_by.full_name}`}
        </p>
        {t.movement && <FlagChips flags={t.movement.flags} hide={["CORRECTED"]} />}
      </div>
    </li>
  );
}

export function VehicleDetailPage() {
  const { plate: raw } = useParams();
  const plate = raw ? normalizePlate(decodeURIComponent(raw)) : null;
  const { token, user } = useSession();
  const notify = useToast();
  const invalidate = useInvalidate();
  const isAdmin = user.role === "ADMIN";
  const history = useHistory(plate);
  const registered = history.data?.registered ?? false;
  const vehicle = useVehicle(plate, registered);
  const [dialog, setDialog] = useState<"link" | "register" | "edit" | "deactivate" | null>(null);
  const [correcting, setCorrecting] = useState<CorrectionTarget | null>(null);

  if (!plate) {
    return (
      <>
        <PageHeader title="Look up a plate" description="Movements and sightings across all gates, with registry details." back={{ to: "/vehicles", label: "Vehicles" }} />
        <Lookup />
      </>
    );
  }

  const h = history.data;
  const v = vehicle.data?.vehicle;

  return (
    <>
      <PageHeader
        back={{ to: "/vehicles", label: "Vehicles" }}
        title={
          <div className="flex flex-wrap items-center gap-3">
            <span className="plate tracking-widest">{plate}</span>
            {v && (
              <ReasonCodeBadge
                code={determineReasonCode({
                  vehicle: {
                    id: v.id,
                    plate: v.plate,
                    raw_plate: v.raw_plate,
                    category: v.category,
                    registry_status: v.status,
                    is_active: v.is_active,
                    make_model: v.make_model,
                    color: v.color,
                    valid_from: v.valid_from,
                    valid_until: v.valid_until,
                  },
                  status: v.status,
                  linkStatus: registered ? "LINKED" : "NOT_LINKED",
                })}
              />
            )}
          </div>
        }
        description={
          h ? (
            h.owner ? (
              <>
                <Link to={`/owners/${h.owner.id}`} className="link">
                  {h.owner.name}
                </Link>{" "}
                · {h.owner.institutional_id} · {humanize(h.residence?.person_type)}
                {h.residence?.residence_type ? ` · ${humanize(h.residence.residence_type)}` : ""}
                {h.residence?.residence ? `, ${h.residence.residence}` : ""}
              </>
            ) : registered ? (
              "Registered, no owner on record"
            ) : (
              "Not in the registry"
            )
          ) : undefined
        }
        actions={
          h &&
          (registered ? (
            isAdmin && (
              <>
                <Button icon={<Pencil className="h-4 w-4" />} disabled={!vehicle.data} onClick={() => setDialog("edit")}>
                  Edit
                </Button>
                {v && v.status !== "INACTIVE" && (
                  <Button icon={<Ban className="h-4 w-4" />} onClick={() => setDialog("deactivate")}>
                    Deactivate
                  </Button>
                )}
              </>
            )
          ) : (
            <>
              <Button variant="primary" icon={<Link2 className="h-4 w-4" />} onClick={() => setDialog("link")}>
                Link to owner
              </Button>
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setDialog("register")}>
                Register
              </Button>
            </>
          ))
        }
      />

      {history.isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-32 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : history.isError ? (
        <div className="card">
          <ErrorState error={history.error} onRetry={() => void history.refetch()} />
        </div>
      ) : (
        h && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-1">
              <Section title="Presence">
                <p className="text-lg font-semibold text-slate-900 dark:text-white">{PRESENCE_LABEL[h.presence.status]}</p>
                {h.presence.last_movement && (
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                    {MOVEMENT_LABEL[h.presence.last_movement.direction]} at {h.presence.last_movement.gate.name}, {formatDateTime(h.presence.last_movement.timestamp)}
                  </p>
                )}
                <div className="mt-2">
                  <FlagChips flags={h.presence.flags} />
                </div>
              </Section>

              <Section title="Registry">
                {registered ? (
                  vehicle.isLoading ? (
                    <Skeleton className="h-24" />
                  ) : v ? (
                    <DetailList className="sm:grid-cols-2 lg:grid-cols-2">
                      <Detail label="Status" value={<RegistryStatus status={v.status} />} />
                      <Detail label="Category" value={humanize(v.category)} />
                      <Detail label="Vehicle" value={[v.color, v.make_model].filter(Boolean).join(" ")} />
                      <Detail label="Within validity" value={v.is_active ? "Yes" : "No"} />
                      <Detail label="Valid from" value={v.valid_from ? formatDateTime(v.valid_from) : null} />
                      <Detail label="Valid until" value={v.valid_until ? formatDateTime(v.valid_until) : null} />
                      <div className="col-span-2">
                        <Detail label="Notes" value={v.notes} />
                      </div>
                    </DetailList>
                  ) : (
                    <ErrorState error={vehicle.error} />
                  )
                ) : (
                  <EmptyState
                    className="py-6"
                    title="Not in the registry"
                    description="Link it to an owner after checking ID, or register it as a visitor or delivery vehicle."
                  />
                )}
              </Section>

              {h.link_events.length > 0 && (
                <Section title="Owner links" description="Human assertions, not proof of identity.">
                  <ul className="space-y-3 text-sm">
                    {h.link_events.map((l) => (
                      <li key={l.id}>
                        <p className="text-slate-800 dark:text-slate-200">“{l.evidence_note}”</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {formatDateTime(l.linked_at)} · {l.linked_by.full_name} ({humanize(l.method)}){l.expires_at ? ` · expires ${formatDateTime(l.expires_at)}` : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}
            </div>

            <Section className="lg:col-span-2" title={`Timeline · all gates (${h.timeline.length})`} description="Logged movements and sightings, newest first.">
              {h.timeline.length === 0 ? (
                <EmptyState title="No movements or sightings recorded for this plate" />
              ) : (
                <ol>
                  {h.timeline.map((t) => (
                    <TimelineRow key={(t.movement?.id ?? t.sighting?.observation.id) as string} t={t} onCorrect={setCorrecting} />
                  ))}
                </ol>
              )}
            </Section>
          </div>
        )
      )}

      {!history.isLoading && (
        <div className="mt-8">
          <p className="label mb-2">Look up another plate</p>
          <Lookup />
        </div>
      )}

      {dialog === "link" && h && (
        <LinkOwnerDialog
          token={token}
          role={user.role}
          plate={h.normalized_plate}
          onClose={() => setDialog(null)}
          onLinked={(m) => {
            setDialog(null);
            notify(m);
          }}
        />
      )}
      {dialog === "register" && h && (
        <RegisterVehicleDialog
          token={token}
          role={user.role}
          plate={h.normalized_plate}
          onClose={() => setDialog(null)}
          onRegistered={(m) => {
            setDialog(null);
            notify(m);
          }}
        />
      )}
      {dialog === "edit" && vehicle.data && (
        <VehicleEditDialog
          token={token}
          detail={vehicle.data}
          onClose={() => setDialog(null)}
          onSaved={(m) => {
            setDialog(null);
            notify(m);
          }}
        />
      )}
      {dialog === "deactivate" && v && (
        <ConfirmDialog
          title={`Deactivate ${v.plate}?`}
          message={
            <>
              <p>The registration is set to INACTIVE. Nothing is deleted: its movements, sightings and links stay in the record.</p>
              <p>To correct a plate, deactivate it and register the vehicle again under the right plate.</p>
            </>
          }
          confirmLabel="Deactivate"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deactivateVehicle(token, v.plate);
            await invalidate(...REGISTRY_ROOTS);
            setDialog(null);
            notify(`${v.plate} is now INACTIVE.`);
          }}
        />
      )}
      {correcting && (
        <CorrectionDialog
          token={token}
          target={correcting}
          onClose={() => setCorrecting(null)}
          onCorrected={() => {
            setCorrecting(null);
            notify("Correction recorded.");
          }}
        />
      )}
    </>
  );
}
