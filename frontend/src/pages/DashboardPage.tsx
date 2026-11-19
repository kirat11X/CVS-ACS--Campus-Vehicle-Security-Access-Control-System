import {
  AlertCircle,
  ArrowLeftFromLine,
  ArrowRight,
  ArrowRightToLine,
  Building2,
  Camera,
  Car,
  CircleDot,
  Database,
  Package,
  Radio,
  Server,
  Unlink,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useDashboard, useGates, useHealth, useLanes, useLogs } from "../api/queries";
import { useSession } from "../auth/AuthContext";
import { ActivityChart } from "../components/charts/ActivityChart";
import { CONNECTION_DISPLAY } from "../components/feed/ConnectionIndicator";
import { FlagChips } from "../components/movement/FlagChips";
import { MovementLabel } from "../components/movement/MovementLabel";
import { SubjectCell } from "../components/movement/SubjectCell";
import { GateStatusBadge, LinkStatusBadge } from "../components/registry/StatusBadges";
import { ButtonLink } from "../components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/Feedback";
import { FilterChips, PageHeader, Section, StatTile } from "../components/ui/Layout";
import { useFeed } from "../feed/LiveFeedContext";
import { cx } from "../lib/cx";
import { DIRECTION_REASON, compactNumber, formatFeedTimestamp, formatRelative } from "../lib/format";
import { directionSource } from "../lib/gates";
import { useNow } from "../lib/hooks";

type Range = "today" | "24h" | "7d";

/** Window start, snapped to local boundaries so buckets line up with the clock. */
function rangeStart(range: Range, now: number): string {
  const d = new Date(now);
  if (range === "24h") {
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() - 23);
  } else {
    d.setHours(0, 0, 0, 0);
    if (range === "7d") d.setDate(d.getDate() - 6);
  }
  return d.toISOString();
}

const RANGE_LABEL: Record<Range, string> = { today: "today", "24h": "in the last 24 hours", "7d": "in the last 7 days" };


function HealthRow({ icon, label, ok, detail }: { icon: ReactNode; label: string; ok: boolean | null; detail: string }) {
  return (
    <li className="flex items-center gap-3 py-2.5">
      <span className="text-slate-400">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-slate-900 dark:text-white">{label}</span>
        <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{detail}</span>
      </span>
      <span
        className={cx(
          "inline-flex items-center gap-1.5 text-xs font-medium",
          ok === null ? "text-slate-400" : ok ? "text-slate-700 dark:text-slate-200" : "text-slate-900 dark:text-white",
        )}
      >
        <span className={cx("h-2 w-2 rounded-full", ok === null ? "bg-slate-300" : ok ? "bg-sky-500" : "bg-amber-500")} aria-hidden />
        {ok === null ? "Checking" : ok ? "OK" : "Problem"}
      </span>
    </li>
  );
}

export function DashboardPage() {
  const { user } = useSession();
  const [range, setRange] = useState<Range>("today");
  const now = useNow(60_000);
  const since = useMemo(() => rangeStart(range, now), [range, now]);
  const summary = useDashboard(since);
  const gates = useGates();
  const lanes = useLanes();
  const health = useHealth(30_000);
  const recent = useLogs({ limit: 6 });
  const feed = useFeed();
  const [greeting, setGreeting] = useState("");

  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening");
  }, []);

  const s = summary.data;
  const loading = summary.isLoading;
  const value = (n: number | undefined) => (n === undefined ? "—" : compactNumber(n));

  const attention = useMemo(
    () =>
      feed.cards
        .filter((c) => (c.item.link_status === "LOW_CONFIDENCE" && !c.item.resolution) || (!c.item.movement && c.item.movement_status === "DIRECTION_UNKNOWN"))
        .slice(0, 5),
    [feed.cards],
  );

  const liveGates = (gates.data ?? []).filter((g) => g.status !== "INACTIVE");
  const h = health.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${greeting}, ${user.full_name.split(" ")[0]}`}
        description="Registry and movement context across all gates. Nothing here opens or closes a barrier; guards decide at the gate."
      />

      <FilterChips<Range>
        label="Time range"
        value={range}
        onChange={setRange}
        options={[
          { value: "today", label: "Today" },
          { value: "24h", label: "Last 24 hours" },
          { value: "7d", label: "Last 7 days" },
        ]}
      />

      {summary.isError && !s ? (
        <div className="card">
          <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4">
          <StatTile
            label="Vehicles on campus"
            value={value(s?.presence.inside)}
            sub={s ? `${s.presence.inside_linked} linked · ${s.presence.inside_unlinked} not linked` : undefined}
            icon={<Building2 className="h-4 w-4" />}
            to="/inside"
            loading={loading}
          />
          <StatTile label="Entries" value={value(s?.movements.entries)} sub={RANGE_LABEL[range]} icon={<ArrowRightToLine className="h-4 w-4" />} to="/logs?direction=ENTRY" loading={loading} />
          <StatTile label="Exits" value={value(s?.movements.exits)} sub={RANGE_LABEL[range]} icon={<ArrowLeftFromLine className="h-4 w-4" />} to="/logs?direction=EXIT" loading={loading} />
          <StatTile
            label="Sightings"
            value={value(s?.observations.total)}
            sub={s ? `${s.observations.camera} camera · ${s.observations.manual} manual` : undefined}
            icon={<Camera className="h-4 w-4" />}
            to="/feed"
            loading={loading}
          />
          <StatTile
            label="Plates to review"
            value={value(s?.observations.low_confidence_unresolved)}
            sub="uncertain reads, unconfirmed"
            icon={<AlertCircle className="h-4 w-4" />}
            to="/feed?status=REVIEW"
            loading={loading}
          />
          <StatTile
            label="Unlinked on campus"
            value={value(s?.presence.inside_unlinked)}
            sub="plates not in the registry, inside now"
            icon={<Unlink className="h-4 w-4" />}
            to="/inside"
            loading={loading}
          />
          <StatTile
            label="Delivery flags"
            value={value(s?.delivery_flags)}
            sub="REVIEW / ALERT awaiting a guard"
            icon={<Package className="h-4 w-4" />}
            to="/deliveries?decision=OPEN"
            loading={loading}
          />
          <StatTile
            label="Registered vehicles"
            value={value(s?.registry.vehicles)}
            sub={s ? `${s.registry.temporary_active} visitor / delivery passes active` : undefined}
            icon={<Car className="h-4 w-4" />}
            to="/vehicles"
            loading={loading}
          />
        </div>
      )}

      <Section
        title={s && s.bucket_minutes >= 1440 ? "Movements per day" : "Movements per hour"}
        description="Effective movement log (latest corrections applied), all gates."
      >
        {s ? (
          <ActivityChart buckets={s.activity} bucketMinutes={s.bucket_minutes} fetching={summary.isFetching && !loading} />
        ) : (
          <Skeleton className="h-[230px] w-full" />
        )}
      </Section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <Section
          className="lg:col-span-3"
          title="Needs attention"
          description="From the live feed: uncertain reads and sightings with no recorded direction."
          actions={
            <ButtonLink to="/feed" size="sm" variant="ghost">
              Open live feed <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </ButtonLink>
          }
          bodyClassName="p-0"
        >
          {attention.length === 0 ? (
            <EmptyState icon={<CircleDot className="h-5 w-5" />} title="Nothing waiting" description="New uncertain reads and unknown directions appear here as they arrive." />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {attention.map(({ item }) => {
                const reason = typeof item.direction?.evidence?.reason === "string" ? DIRECTION_REASON[item.direction.evidence.reason as string] : undefined;
                return (
                  <li key={item.observation.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 sm:px-5">
                    <span className="whitespace-nowrap text-xs tabular-nums text-slate-500 dark:text-slate-400">{formatFeedTimestamp(item.observation.observed_at, false)}</span>
                    <span className="plate min-w-24 text-sm text-slate-900 dark:text-white">{item.observation.plate.normalized ?? "No plate"}</span>
                    <LinkStatusBadge status={item.link_status} short />
                    <span className="min-w-0 flex-1 truncate text-xs text-slate-500 dark:text-slate-400">
                      {item.observation.gate.name}
                      {!item.movement && item.movement_status === "DIRECTION_UNKNOWN" ? ` · direction unknown${reason ? ` (${reason})` : ""}` : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </Section>

        <Section
          className="lg:col-span-2"
          title="System"
          actions={
            <ButtonLink to="/system" size="sm" variant="ghost">
              Details <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </ButtonLink>
          }
          bodyClassName="px-4 sm:px-5"
        >
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            <HealthRow
              icon={<Database className="h-4 w-4" />}
              label="Database"
              ok={h ? h.database.status === "ok" : health.isError ? false : null}
              detail={h ? (h.database.status === "ok" ? "PostgreSQL reachable" : String(h.database.detail ?? "error")) : health.isError ? "Backend unreachable" : "…"}
            />
            <HealthRow
              icon={<Server className="h-4 w-4" />}
              label="MQTT broker"
              ok={h ? h.mqtt.status === "ok" : health.isError ? false : null}
              detail={h ? (h.mqtt.status === "ok" ? `Round trip ${String(h.mqtt.latency_ms ?? "?")} ms` : String(h.mqtt.detail ?? "error")) : "…"}
            />
            <HealthRow
              icon={<Camera className="h-4 w-4" />}
              label="Frigate ingestion"
              ok={h ? h.frigate_worker.running && h.frigate_worker.connected : health.isError ? false : null}
              detail={
                h
                  ? `${h.frigate_worker.connected ? "Subscribed to" : "Not connected to"} ${h.frigate_worker.topic} · ${h.frigate_worker.stats.messages_received ?? 0} messages`
                  : "…"
              }
            />
            <HealthRow
              icon={<Radio className="h-4 w-4" />}
              label="Live stream"
              ok={feed.connection === "live" ? true : feed.connection === "connecting" ? null : false}
              detail={CONNECTION_DISPLAY[feed.connection].detail}
            />
          </ul>
        </Section>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <Section
          className="lg:col-span-3"
          title="Recent movements"
          actions={
            <ButtonLink to="/logs" size="sm" variant="ghost">
              Movement log <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </ButtonLink>
          }
          bodyClassName="p-0"
        >
          {recent.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : recent.isError ? (
            <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />
          ) : (recent.data?.items.length ?? 0) === 0 ? (
            <EmptyState title="No movements yet" description="Movements are logged when a declared lane role, zone order or guard gives a direction." />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {recent.data!.items.map((m) => (
                <li key={m.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 sm:px-5">
                  <span className="w-20 text-xs tabular-nums text-slate-500 dark:text-slate-400" title={m.timestamp}>
                    {formatRelative(m.timestamp, now)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <SubjectCell plate={m.normalized_plate} vehicle={m.vehicle} owner={m.owner} residence={m.residence} />
                  </div>
                  <div className="text-xs">
                    <MovementLabel direction={m.direction} method={m.direction_method} corrected={m.corrected} />
                    <div className="mt-0.5 text-slate-500 dark:text-slate-400">{m.gate.name}</div>
                  </div>
                  <FlagChips flags={m.flags} hide={["CORRECTED"]} />
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          className="lg:col-span-2"
          title="Gates & direction sources"
          actions={
            <ButtonLink to="/gates" size="sm" variant="ghost">
              Configure <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </ButtonLink>
          }
          bodyClassName="p-0"
        >
          {gates.isLoading || lanes.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {liveGates.map((g) => {
                const src = directionSource(g, lanes.data ?? []);
                return (
                  <li key={g.id} className="px-4 py-3 sm:px-5">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900 dark:text-white">{g.name}</span>
                      <GateStatusBadge status={g.status} />
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                      <span className="font-mono">{g.camera_id ?? "—"}</span> ·{" "}
                      <span className={cx(!src.declared && "font-medium text-slate-800 dark:text-slate-200")}>{src.label}</span>
                      {src.extra.length > 0 && ` · +${src.extra.length} more camera${src.extra.length > 1 ? "s" : ""}`}
                    </p>
                  </li>
                );
              })}
              {liveGates.length === 0 && <EmptyState title="No gates configured" />}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
