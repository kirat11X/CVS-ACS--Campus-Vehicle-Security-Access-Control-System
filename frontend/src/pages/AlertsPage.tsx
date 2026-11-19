import { ArrowRight, BellRing, Car, Package, RefreshCw, Volume2, VolumeX } from "lucide-react";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";
import { useAlerts } from "../api/queries";
import type { AlertItem, AlertSeverity } from "../api/types";
import { Button } from "../components/ui/Button";
import { Badge, EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { FilterChips, PageHeader } from "../components/ui/Layout";
import { cx } from "../lib/cx";
import { ALERT_KIND_LABEL, SEVERITY_STYLE, formatDateTime, formatRelative } from "../lib/format";
import { useNow } from "../lib/hooks";
import { useSoundAlerts } from "../lib/soundAlerts";

type KindFilter = "ALL" | "PLATES" | "DELIVERIES";
type SeverityFilter = AlertSeverity | "ALL";

const isPlate = (a: AlertItem) => a.kind === "PLATE_REVIEW" || a.kind === "PLATE_UNLINKED" || a.kind === "OVERSTAY_UNLINKED";

/** Where the guard acts on an alert: the plate's page / review queue, or the delivery's item list. */
function alertTarget(a: AlertItem): string {
  if (a.kind === "PLATE_REVIEW") return `/feed?status=REVIEW&plate=${encodeURIComponent(a.ref)}`;
  if (a.kind === "OVERSTAY_UNLINKED") return `/inside?q=${encodeURIComponent(a.ref)}`;
  if (a.kind === "PLATE_UNLINKED") return `/vehicles/${encodeURIComponent(a.ref)}`;
  return `/deliveries/${encodeURIComponent(a.ref)}`;
}

export function AlertsPage() {
  const alerts = useAlerts(100, 15_000);
  const now = useNow(30_000);
  const { soundEnabled, toggleSound, testSound } = useSoundAlerts();
  const [params, setParams] = useSearchParams();
  const kind = (params.get("kind") as KindFilter | null) ?? "ALL";
  const severity = (params.get("severity") as SeverityFilter | null) ?? "ALL";
  const setParam = (key: string, value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value === "ALL") next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );

  const all = useMemo(() => alerts.data ?? [], [alerts.data]);
  const byKind = all.filter((a) => kind === "ALL" || (kind === "PLATES" ? isPlate(a) : !isPlate(a)));
  const visible = byKind.filter((a) => severity === "ALL" || a.severity === severity);
  const counts = useMemo(() => {
    const out: Record<SeverityFilter, number> = { ALL: byKind.length, HIGH: 0, MEDIUM: 0, LOW: 0 };
    for (const a of byKind) out[a.severity]++;
    return out;
  }, [byKind]);

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Everything that needs a guard's attention: plates to review, unlinked plates, and delivery lines flagged REVIEW or ALERT without a decision. Alerts inform; they never block anyone."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<Volume2 className="h-3.5 w-3.5 text-slate-600 dark:text-slate-400" />}
              onClick={testSound}
              title="Test audio alert chime on speaker"
            >
              Test Sound
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={
                soundEnabled ? (
                  <Volume2 className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                ) : (
                  <VolumeX className="h-3.5 w-3.5 text-slate-400" />
                )
              }
              onClick={toggleSound}
              title={soundEnabled ? "Mute alert audio" : "Enable alert audio"}
            >
              {soundEnabled ? "Sound: ON" : "Muted"}
            </Button>
            <Button
              size="sm"
              icon={<RefreshCw className={cx("h-3.5 w-3.5", alerts.isFetching && "animate-spin")} />}
              onClick={() => void alerts.refetch()}
            >
              Refresh
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <FilterChips<KindFilter>
          label="Kind"
          value={kind}
          onChange={(v) => setParam("kind", v)}
          options={[
            { value: "ALL", label: "All", count: all.length },
            { value: "PLATES", label: "Plates", count: all.filter(isPlate).length },
            { value: "DELIVERIES", label: "Deliveries", count: all.filter((a) => !isPlate(a)).length },
          ]}
        />
        <FilterChips<SeverityFilter>
          label="Severity"
          value={severity}
          onChange={(v) => setParam("severity", v)}
          options={(["ALL", "HIGH", "MEDIUM", "LOW"] as SeverityFilter[]).map((s) => ({
            value: s,
            label: s === "ALL" ? "Any severity" : s.charAt(0) + s.slice(1).toLowerCase(),
            count: counts[s],
          }))}
        />
      </div>

      <div className="card overflow-hidden">
        {alerts.isLoading ? (
          <SkeletonRows rows={6} />
        ) : alerts.isError && !alerts.data ? (
          <ErrorState error={alerts.error} onRetry={() => void alerts.refetch()} />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<BellRing className="h-5 w-5" />}
            title={all.length === 0 ? "Nothing needs attention" : "Nothing matches these filters"}
            description={all.length === 0 ? "Uncertain plate reads, unlinked plates and flagged delivery lines appear here." : "Clear a filter to see more."}
          />
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {visible.map((a, i) => (
              <li key={`${a.kind}-${a.ref}-${a.at}-${i}`}>
                <Link
                  to={alertTarget(a)}
                  className="flex items-start gap-3 px-4 py-3 hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none dark:hover:bg-slate-800/50 dark:focus-visible:bg-slate-800/50 sm:px-5"
                >
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                    {isPlate(a) ? <Car className="h-4 w-4" aria-hidden /> : <Package className="h-4 w-4" aria-hidden />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className={SEVERITY_STYLE[a.severity]}>{a.severity}</Badge>
                      <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{ALERT_KIND_LABEL[a.kind] ?? a.kind}</span>
                      <span className={cx("text-sm text-slate-900 dark:text-white", isPlate(a) ? "plate" : "font-mono font-semibold")}>{a.ref}</span>
                    </div>
                    <p className="mt-1 text-sm font-medium text-slate-900 dark:text-white">{a.title}</p>
                    {a.detail && <p className="text-xs text-slate-500 dark:text-slate-400">{a.detail}</p>}
                  </div>
                  <div className="shrink-0 text-right text-xs text-slate-500 dark:text-slate-400">
                    <div title={formatDateTime(a.at)}>{formatRelative(a.at, now)}</div>
                    {a.gate_id && <div className="mt-0.5">{a.gate_id}</div>}
                  </div>
                  <ArrowRight className="mt-1 hidden h-4 w-4 shrink-0 text-slate-400 sm:block" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
