import { ChevronDown, Download, Filter, History, PencilLine, ScrollText } from "lucide-react";
import { Fragment, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { useGates, useLogDetail, useLogs } from "../api/queries";
import type { MovementEntry } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { CorrectionDialog, type CorrectionTarget } from "../components/forms/CorrectionDialog";
import { FlagChips } from "../components/movement/FlagChips";
import { MovementLabel } from "../components/movement/MovementLabel";
import { SubjectCell } from "../components/movement/SubjectCell";
import { ReasonCodeBadge, determineReasonCode } from "../components/ReasonCodeBadge";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, Spinner, SkeletonRows, errorMessage } from "../components/ui/Feedback";
import { Field, Input, Select } from "../components/ui/Form";
import { PageHeader, Pagination, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { downloadText, toCsv } from "../lib/csv";
import { cx } from "../lib/cx";
import { METHOD_LABEL, MOVEMENT_LABEL, formatDateTime } from "../lib/format";

const PAGE_SIZE = 50;
const EXPORT_MAX = 2000;
const KEYS = ["plate", "gate_id", "direction", "date_from", "date_to", "linked"] as const;
type Filters = Record<(typeof KEYS)[number], string>;

const toIso = (local: string) => (local ? new Date(local).toISOString() : undefined);

function RecordRows({ id }: { id: string }) {
  const detail = useLogDetail(id);
  if (detail.isLoading) return <Spinner />;
  if (detail.isError) return <span className="text-xs text-slate-600">{errorMessage(detail.error)}</span>;
  return (
    <ol className="space-y-1.5 text-xs text-slate-700 dark:text-slate-300">
      {detail.data!.rows.map((r, i) => (
        <li key={r.id} className="flex flex-wrap gap-x-2">
          <span className="font-semibold">{i === 0 ? "Original" : `Correction ${i}`}</span>
          <span className="text-slate-500 dark:text-slate-400">{formatDateTime(r.created_at)}</span>
          <span>
            {MOVEMENT_LABEL[r.direction]} ({METHOD_LABEL[r.direction_method]})
          </span>
          <span>
            plate <span className="font-mono">{r.normalized_plate ?? "none"}</span>
            {r.plate_source === "GUARD_CORRECTION" ? " (guard)" : ""}
          </span>
          <span className="text-slate-500 dark:text-slate-400">by {r.created_by?.full_name ?? "system"}</span>
          {r.note && <span className="italic">“{r.note}”</span>}
        </li>
      ))}
    </ol>
  );
}

function RowActions({ m, open, onToggle, onCorrect }: { m: MovementEntry; open: boolean; onToggle: () => void; onCorrect: () => void }) {
  const plate = m.vehicle?.plate ?? m.normalized_plate;
  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      <Button size="sm" variant="ghost" onClick={onToggle} aria-expanded={open}>
        <ChevronDown className={cx("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden />
        Record
      </Button>
      <Button size="sm" variant="ghost" icon={<PencilLine className="h-3.5 w-3.5" />} onClick={onCorrect}>
        Correct
      </Button>
      {plate && (
        <Link to={`/vehicles/${encodeURIComponent(plate)}`} className="btn btn-ghost btn-sm">
          <History className="h-3.5 w-3.5" aria-hidden />
          History
        </Link>
      )}
    </div>
  );
}

export function MovementLogPage() {
  const { token } = useSession();
  const notify = useToast();
  const gates = useGates();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(KEYS.map((k) => [k, params.get(k) ?? ""])) as Filters;
  const skip = Math.max(0, Number(params.get("skip")) || 0);
  const [draft, setDraft] = useState<Filters>(filters);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [correcting, setCorrecting] = useState<CorrectionTarget | null>(null);
  const [exporting, setExporting] = useState(false);

  const query = {
    plate: filters.plate.trim() || undefined,
    gate_id: filters.gate_id || undefined,
    direction: filters.direction || undefined,
    date_from: toIso(filters.date_from),
    date_to: toIso(filters.date_to),
    linked: filters.linked || undefined,
  };
  const logs = useLogs({ ...query, skip, limit: PAGE_SIZE });
  const active = KEYS.filter((k) => filters[k]).length;

  const write = (next: Filters, nextSkip = 0) => {
    const p = new URLSearchParams();
    for (const k of KEYS) if (next[k]) p.set(k, next[k]);
    if (nextSkip) p.set("skip", String(nextSkip));
    setParams(p, { replace: true });
    setExpanded(new Set());
  };

  const apply = (e: FormEvent) => {
    e.preventDefault();
    write(draft);
    setFiltersOpen(false);
  };

  const clear = () => {
    const empty = Object.fromEntries(KEYS.map((k) => [k, ""])) as Filters;
    setDraft(empty);
    write(empty);
  };

  const toggle = (id: string) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const exportCsv = async () => {
    setExporting(true);
    try {
      const rows: MovementEntry[] = [];
      for (let offset = 0; offset < EXPORT_MAX; offset += 200) {
        const page = await api.logs(token, { ...query, skip: offset, limit: 200 });
        rows.push(...page.items);
        if (offset + 200 >= page.total) break;
      }
      const csv = toCsv(
        ["time", "gate", "movement", "direction_source", "plate", "plate_source", "linked", "owner", "owner_id", "category", "flags", "corrected", "recorded_by", "note"],
        rows.map((m) => [
          m.timestamp,
          m.gate.name,
          m.direction,
          m.direction_method,
          m.normalized_plate,
          m.plate_source,
          m.linked,
          m.owner?.name,
          m.owner?.institutional_id,
          m.vehicle?.category,
          m.flags.join(" "),
          m.corrected,
          m.recorded_by?.full_name,
          m.note,
        ]),
      );
      downloadText(`movement-log-${new Date().toISOString().slice(0, 10)}.csv`, csv);
      notify(`Exported ${rows.length} movement${rows.length === 1 ? "" : "s"}.`);
    } catch (e) {
      notify(errorMessage(e, "Export failed."), "info");
    } finally {
      setExporting(false);
    }
  };

  const filterForm = (
    <form onSubmit={apply} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6">
      <Field label="Plate">
        <Input className="plate" value={draft.plate} onChange={(e) => setDraft({ ...draft, plate: e.target.value })} autoCapitalize="characters" />
      </Field>
      <Field label="Gate">
        <Select value={draft.gate_id} onChange={(e) => setDraft({ ...draft, gate_id: e.target.value })}>
          <option value="">All gates</option>
          {(gates.data ?? []).map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Movement">
        <Select value={draft.direction} onChange={(e) => setDraft({ ...draft, direction: e.target.value })}>
          <option value="">Both</option>
          <option value="ENTRY">{MOVEMENT_LABEL.ENTRY}</option>
          <option value="EXIT">{MOVEMENT_LABEL.EXIT}</option>
        </Select>
      </Field>
      <Field label="From">
        <Input type="datetime-local" value={draft.date_from} onChange={(e) => setDraft({ ...draft, date_from: e.target.value })} />
      </Field>
      <Field label="To">
        <Input type="datetime-local" value={draft.date_to} onChange={(e) => setDraft({ ...draft, date_to: e.target.value })} />
      </Field>
      <Field label="Registry link">
        <Select value={draft.linked} onChange={(e) => setDraft({ ...draft, linked: e.target.value })}>
          <option value="">Any</option>
          <option value="true">Linked</option>
          <option value="false">Not linked</option>
        </Select>
      </Field>
      <div className="flex gap-2 sm:col-span-2 lg:col-span-6 lg:justify-end">
        <Button type="button" onClick={clear}>
          Clear
        </Button>
        <Button type="submit" variant="primary">
          Apply filters
        </Button>
      </div>
    </form>
  );

  const items = logs.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Movement log"
        description="Entries and exits across all gates. Corrections are added as new records; the latest one is shown and the original is kept."
        actions={
          <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} loading={exporting} disabled={!logs.data?.total} onClick={() => void exportCsv()}>
            Export CSV
          </Button>
        }
      />

      <div className="mb-4 lg:hidden">
        <Button onClick={() => setFiltersOpen((o) => !o)} aria-expanded={filtersOpen} icon={<Filter className="h-4 w-4" />}>
          Filters{active ? ` (${active})` : ""}
        </Button>
      </div>
      <div className={cx("card mb-4 p-4", !filtersOpen && "hidden lg:block")}>{filterForm}</div>

      <Section bodyClassName="p-0">
        {logs.isLoading ? (
          <SkeletonRows rows={8} />
        ) : logs.isError ? (
          <ErrorState error={logs.error} onRetry={() => void logs.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState icon={<ScrollText className="h-5 w-5" />} title={active ? "No movements match these filters" : "No movements logged yet"} />
        ) : (
          <div className={cx(logs.isPlaceholderData && "opacity-60")}>
            <table className="hidden min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800 lg:table">
              <thead className="table-head">
                <tr>
                  <th className="px-4 py-2.5">Time</th>
                  <th className="px-4 py-2.5">Gate</th>
                  <th className="px-4 py-2.5">Movement</th>
                  <th className="px-4 py-2.5">Vehicle</th>
                  <th className="px-4 py-2.5">Context</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map((m) => {
                  const open = expanded.has(m.id);
                  return (
                    <Fragment key={m.id}>
                      <tr className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
                        <td className="whitespace-nowrap px-4 py-3 text-xs tabular-nums text-slate-700 dark:text-slate-300">{formatDateTime(m.timestamp)}</td>
                        <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">{m.gate.name}</td>
                        <td className="px-4 py-3 text-xs">
                          <MovementLabel direction={m.direction} method={m.direction_method} corrected={m.corrected} />
                        </td>
                        <td className="px-4 py-3">
                          <SubjectCell plate={m.normalized_plate} vehicle={m.vehicle} owner={m.owner} residence={m.residence} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <ReasonCodeBadge
                              code={determineReasonCode({
                                plateConfidence: m.direction_confidence,
                                linkStatus: m.linked ? "LINKED" : "NOT_LINKED",
                                vehicle: m.vehicle,
                                flags: m.flags,
                              })}
                              compact
                            />
                            <FlagChips flags={m.flags} hide={["CORRECTED"]} />
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <RowActions
                            m={m}
                            open={open}
                            onToggle={() => toggle(m.id)}
                            onCorrect={() => setCorrecting({ movementId: m.id, direction: m.direction, plate: m.normalized_plate })}
                          />
                        </td>
                      </tr>
                      {open && (
                        <tr className="bg-slate-50 dark:bg-slate-800/40">
                          <td colSpan={6} className="px-4 py-3">
                            <RecordRows id={m.id} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>

            <ul className="divide-y divide-slate-100 dark:divide-slate-800 lg:hidden">
              {items.map((m) => {
                const open = expanded.has(m.id);
                return (
                  <li key={m.id} className="space-y-2 px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <SubjectCell plate={m.normalized_plate} vehicle={m.vehicle} owner={m.owner} residence={m.residence} />
                      <span className="shrink-0 text-right text-[11px] tabular-nums text-slate-500 dark:text-slate-400">{formatDateTime(m.timestamp)}</span>
                    </div>
                    <div className="text-xs">
                      <MovementLabel direction={m.direction} method={m.direction_method} corrected={m.corrected} />
                      <span className="text-slate-500 dark:text-slate-400"> · {m.gate.name}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <ReasonCodeBadge
                        code={determineReasonCode({
                          plateConfidence: m.direction_confidence,
                          linkStatus: m.linked ? "LINKED" : "NOT_LINKED",
                          vehicle: m.vehicle,
                          flags: m.flags,
                        })}
                        compact
                      />
                      <FlagChips flags={m.flags} hide={["CORRECTED"]} />
                    </div>
                    <RowActions
                      m={m}
                      open={open}
                      onToggle={() => toggle(m.id)}
                      onCorrect={() => setCorrecting({ movementId: m.id, direction: m.direction, plate: m.normalized_plate })}
                    />
                    {open && (
                      <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/40">
                        <RecordRows id={m.id} />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Section>

      {logs.data && <Pagination skip={skip} limit={PAGE_SIZE} count={items.length} total={logs.data.total} onChange={(s) => write(filters, s)} />}

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
