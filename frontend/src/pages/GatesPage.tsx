import { Ban, Cctv, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { useGates, useInvalidate, useLanes } from "../api/queries";
import type { Gate, Lane } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { GateFormDialog } from "../components/forms/GateFormDialog";
import { LaneFormDialog } from "../components/forms/LaneFormDialog";
import { GateStatusBadge } from "../components/registry/StatusBadges";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/Dialog";
import { Badge, Callout, EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { Switch } from "../components/ui/Form";
import { PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { LANE_ROLE_LABEL, formatDateTime } from "../lib/format";
import { directionSource } from "../lib/gates";

type DialogState =
  | { type: "gate"; gate: Gate | null }
  | { type: "lane"; lane: Lane | null; camera?: string; gate?: string }
  | { type: "deactivate"; gate: Gate }
  | null;

export function GatesPage() {
  const { token, user } = useSession();
  const notify = useToast();
  const invalidate = useInvalidate();
  const isAdmin = user.role === "ADMIN";
  const gates = useGates();
  const lanes = useLanes();
  const [showRetired, setShowRetired] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);

  const allGates = gates.data ?? [];
  const shown = allGates.filter((g) => showRetired || g.status !== "INACTIVE");
  const retired = allGates.length - allGates.filter((g) => g.status !== "INACTIVE").length;
  const allLanes = lanes.data ?? [];
  const gateName = (id: string) => allGates.find((g) => g.id === id)?.name ?? id;
  const undeclared = shown.filter((g) => g.status !== "INACTIVE" && g.camera_id && !directionSource(g, allLanes).declared);

  return (
    <>
      <PageHeader
        title="Gates & cameras"
        description="Each gate maps a Frigate camera to a campus entry point. Movement direction comes only from a declared lane role, a declared zone order, or a guard."
        actions={
          isAdmin && (
            <>
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setDialog({ type: "lane", lane: null })}>
                Declare lane
              </Button>
              <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setDialog({ type: "gate", gate: null })}>
                Add gate
              </Button>
            </>
          )
        }
      />

      {undeclared.length > 0 && (
        <div className="mb-6">
          <Callout tone="notice" title={`${undeclared.length} camera${undeclared.length > 1 ? "s have" : " has"} no declared direction`}>
            Sightings from {undeclared.map((g) => g.camera_id).join(", ")} stay direction-unknown, so no entries or exits are logged for them until a guard confirms
            each one{isAdmin ? " or you declare a lane role" : ""}.
          </Callout>
        </div>
      )}

      <Section
        title="Gates"
        actions={retired > 0 && <Switch checked={showRetired} onChange={setShowRetired} label={<span className="text-xs">Show retired ({retired})</span>} />}
        bodyClassName="p-0"
      >
        {gates.isLoading ? (
          <SkeletonRows rows={3} />
        ) : gates.isError ? (
          <ErrorState error={gates.error} onRetry={() => void gates.refetch()} />
        ) : shown.length === 0 ? (
          <EmptyState icon={<Cctv className="h-5 w-5" />} title="No gates configured" />
        ) : (
          <ul className="grid grid-cols-1 divide-y divide-slate-100 dark:divide-slate-800 md:grid-cols-2 md:divide-y-0 xl:grid-cols-3">
            {shown.map((g) => {
              const src = directionSource(g, allLanes);
              return (
                <li key={g.id} className={cx("p-4 sm:p-5 md:border-b md:border-r md:border-slate-100 md:dark:border-slate-800", g.status === "INACTIVE" && "opacity-60")}>
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-slate-900 dark:text-white">{g.name}</p>
                      <p className="font-mono text-xs text-slate-500 dark:text-slate-400">{g.id}</p>
                    </div>
                    <GateStatusBadge status={g.status} />
                  </div>
                  <dl className="mt-3 space-y-1.5 text-xs">
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-500 dark:text-slate-400">Camera</dt>
                      <dd className="font-mono text-slate-800 dark:text-slate-200">{g.camera_id ?? "—"}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="w-20 shrink-0 text-slate-500 dark:text-slate-400">Direction</dt>
                      <dd className={cx(src.declared ? "text-slate-800 dark:text-slate-200" : "font-medium text-slate-900 dark:text-white")}>{src.label}</dd>
                    </div>
                    {src.extra.length > 0 && (
                      <div className="flex gap-2">
                        <dt className="w-20 shrink-0 text-slate-500 dark:text-slate-400">Also</dt>
                        <dd className="text-slate-800 dark:text-slate-200">
                          {src.extra.map((l) => `${l.camera_id} (${LANE_ROLE_LABEL[l.lane_role]})`).join(", ")}
                        </dd>
                      </div>
                    )}
                    {g.location && (
                      <div className="flex gap-2">
                        <dt className="w-20 shrink-0 text-slate-500 dark:text-slate-400">Location</dt>
                        <dd className="text-slate-800 dark:text-slate-200">{g.location}</dd>
                      </div>
                    )}
                  </dl>
                  {isAdmin && (
                    <div className="mt-3 flex flex-wrap gap-1">
                      <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setDialog({ type: "gate", gate: g })}>
                        Edit
                      </Button>
                      {g.camera_id && g.status !== "INACTIVE" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Cctv className="h-3.5 w-3.5" />}
                          onClick={() => {
                            const lane = allLanes.find((l) => l.camera_id === g.camera_id) ?? null;
                            setDialog({ type: "lane", lane, camera: g.camera_id ?? undefined, gate: g.id });
                          }}
                        >
                          {src.declared ? "Edit lane" : "Declare lane"}
                        </Button>
                      )}
                      {g.status !== "INACTIVE" && (
                        <Button size="sm" variant="ghost" icon={<Ban className="h-3.5 w-3.5" />} onClick={() => setDialog({ type: "deactivate", gate: g })}>
                          Retire
                        </Button>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section className="mt-6" title="Camera lanes" description="Administrator-declared lane roles. Retired lanes are kept for the record." bodyClassName="p-0">
        {lanes.isLoading ? (
          <SkeletonRows rows={3} />
        ) : lanes.isError ? (
          <ErrorState error={lanes.error} onRetry={() => void lanes.refetch()} />
        ) : allLanes.length === 0 ? (
          <EmptyState title="No lanes declared" description="Without a lane role, every camera sighting stays direction-unknown." />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead className="table-head">
                <tr>
                  <th className="px-4 py-2.5">Camera</th>
                  <th className="px-4 py-2.5">Gate</th>
                  <th className="px-4 py-2.5">Role</th>
                  <th className="hidden px-4 py-2.5 md:table-cell">Zones</th>
                  <th className="hidden px-4 py-2.5 lg:table-cell">Updated</th>
                  {isAdmin && <th className="px-4 py-2.5" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {allLanes.map((l) => (
                  <tr key={l.camera_id} className={cx(!l.is_active && "opacity-50")}>
                    <td className="px-4 py-3 font-mono text-xs text-slate-800 dark:text-slate-200">{l.camera_id}</td>
                    <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">{gateName(l.gate_id)}</td>
                    <td className="px-4 py-3 text-xs">
                      <span className="text-slate-800 dark:text-slate-200">{LANE_ROLE_LABEL[l.lane_role]}</span>
                      {!l.is_active && (
                        <Badge className="ml-2 bg-zinc-100 text-zinc-600 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700">Retired</Badge>
                      )}
                    </td>
                    <td className="hidden px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-400 md:table-cell">
                      {l.outside_zone && l.inside_zone ? `${l.outside_zone} → ${l.inside_zone}` : "—"}
                    </td>
                    <td className="hidden px-4 py-3 text-xs text-slate-500 dark:text-slate-400 lg:table-cell">{formatDateTime(l.updated_at)}</td>
                    {isAdmin && (
                      <td className="px-4 py-3 text-right">
                        <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setDialog({ type: "lane", lane: l })}>
                          Edit
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {dialog?.type === "gate" && (
        <GateFormDialog
          token={token}
          gate={dialog.gate}
          onClose={() => setDialog(null)}
          onSaved={(m) => {
            setDialog(null);
            notify(m);
          }}
        />
      )}
      {dialog?.type === "lane" && (
        <LaneFormDialog
          token={token}
          lane={dialog.lane}
          gates={allGates}
          defaultCamera={dialog.camera}
          defaultGate={dialog.gate}
          onClose={() => setDialog(null)}
          onSaved={(m) => {
            setDialog(null);
            notify(m);
          }}
        />
      )}
      {dialog?.type === "deactivate" && (
        <ConfirmDialog
          title={`Retire ${dialog.gate.name}?`}
          message={<p>The gate is set to INACTIVE. Its observations and movements stay in the record, and its camera can be assigned to another gate.</p>}
          confirmLabel="Retire gate"
          onClose={() => setDialog(null)}
          onConfirm={async () => {
            await api.deactivateGate(token, dialog.gate.id);
            await invalidate("gates", "lanes", "dashboard");
            notify(`${dialog.gate.name} retired.`);
            setDialog(null);
          }}
        />
      )}
    </>
  );
}
