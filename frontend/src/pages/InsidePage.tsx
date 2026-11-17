import { Building2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useInside } from "../api/queries";
import type { PresenceEntry } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { CorrectionDialog, type CorrectionTarget } from "../components/forms/CorrectionDialog";
import { FlagChips } from "../components/movement/FlagChips";
import { MovementLabel } from "../components/movement/MovementLabel";
import { SubjectCell } from "../components/movement/SubjectCell";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { SearchInput } from "../components/ui/Form";
import { FilterChips, PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { formatDateTime, formatSince, formatTime } from "../lib/format";
import { useNow } from "../lib/hooks";
import { normalizePlate } from "../app/nav";

type LinkFilter = "all" | "linked" | "unlinked";

function matches(e: PresenceEntry, q: string): boolean {
  if (!q.trim()) return true;
  const plate = normalizePlate(q);
  return (!!plate && (e.normalized_plate ?? "").includes(plate)) || (!!e.owner && e.owner.name.toLowerCase().includes(q.trim().toLowerCase()));
}

export function InsidePage() {
  const { token } = useSession();
  const notify = useToast();
  const inside = useInside();
  const now = useNow(30_000);
  const [linked, setLinked] = useState<LinkFilter>("all");
  const [q, setQ] = useState("");
  const [correcting, setCorrecting] = useState<CorrectionTarget | null>(null);

  const data = inside.data;
  const all = data?.items ?? [];
  const items = all.filter((e) => (linked === "all" || (linked === "linked") === e.linked) && matches(e, q));
  const linkedCount = all.filter((e) => e.linked).length;

  return (
    <>
      <PageHeader
        title="Inside campus"
        description="Derived from each vehicle's latest recorded movement: a vehicle is listed when its last movement is an entry. Refreshes every 15 seconds."
        actions={
          <Button size="sm" icon={<RefreshCw className={inside.isFetching ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />} onClick={() => void inside.refetch()}>
            Refresh
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput label="Search inside" placeholder="Plate or owner name" value={q} onChange={setQ} className="sm:max-w-xs" />
        <FilterChips<LinkFilter>
          label="Registry link"
          value={linked}
          onChange={setLinked}
          options={[
            { value: "all", label: "All", count: all.length },
            { value: "linked", label: "Linked", count: linkedCount },
            { value: "unlinked", label: "Not linked", count: all.length - linkedCount },
          ]}
        />
      </div>

      <Section bodyClassName="p-0">
        {inside.isLoading ? (
          <SkeletonRows rows={6} />
        ) : inside.isError ? (
          <ErrorState error={inside.error} onRetry={() => void inside.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState icon={<Building2 className="h-5 w-5" />} title={all.length ? "No vehicles match" : "No vehicles recorded inside"} />
        ) : (
          <>
            <table className="hidden min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800 md:table">
              <thead className="table-head">
                <tr>
                  <th className="px-4 py-2.5">Vehicle</th>
                  <th className="px-4 py-2.5">Entered</th>
                  <th className="px-4 py-2.5">Inside for</th>
                  <th className="px-4 py-2.5">Gate</th>
                  <th className="px-4 py-2.5">Context</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map((e) => (
                  <tr key={e.subject} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
                    <td className="px-4 py-3">
                      <SubjectCell plate={e.normalized_plate} vehicle={e.vehicle} owner={e.owner} residence={e.residence} />
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {e.last_movement && <MovementLabel direction={e.last_movement.direction} method={e.last_movement.direction_method} />}
                      <div className="text-slate-500 dark:text-slate-400">{e.inside_since ? formatDateTime(e.inside_since) : "—"}</div>
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums text-slate-700 dark:text-slate-300">{e.inside_since ? formatSince(e.inside_since, now) : "—"}</td>
                    <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">{e.last_movement?.gate.name ?? "—"}</td>
                    <td className="px-4 py-3">
                      <FlagChips flags={e.flags} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800 md:hidden">
              {items.map((e) => (
                <li key={e.subject} className="space-y-1.5 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <SubjectCell plate={e.normalized_plate} vehicle={e.vehicle} owner={e.owner} residence={e.residence} />
                    <span className="shrink-0 text-xs font-medium tabular-nums text-slate-700 dark:text-slate-300">{e.inside_since ? formatSince(e.inside_since, now) : "—"}</span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Entered {e.inside_since ? formatDateTime(e.inside_since) : "—"} · {e.last_movement?.gate.name ?? "—"}
                  </p>
                  <FlagChips flags={e.flags} />
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      {data && data.unattributed_entries.length > 0 && (
        <Section className="mt-6" title="Entries without a plate read (last 24 h)" description="These cannot be paired with an exit until a plate is added." bodyClassName="p-0">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.unattributed_entries.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                <span className="tabular-nums text-slate-700 dark:text-slate-300">{formatTime(m.timestamp)}</span>
                <span className="text-slate-600 dark:text-slate-400">{m.gate.name}</span>
                <MovementLabel direction={m.direction} method={m.direction_method} />
                <Button size="sm" className="ml-auto" onClick={() => setCorrecting({ movementId: m.id, direction: m.direction, plate: null })}>
                  Add plate
                </Button>
              </li>
            ))}
          </ul>
        </Section>
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
