import { AlertCircle, Building2, Camera, FlaskConical, LayoutGrid, List, Package, Plus, Radio, Unlink } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import { useDashboard, useGates, useStreamSettings } from "../api/queries";
import type { LinkStatus, PersonType, ResolvedObservation } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { DeliveryScreeningPanel } from "../components/delivery/DeliveryScreeningPanel";
import { ConnectionIndicator } from "../components/feed/ConnectionIndicator";
import { ObservationCard } from "../components/feed/ObservationCard";
import { PlateDetailPanel, PlateRow } from "../components/feed/PlateConsole";
import { CorrectionDialog, type CorrectionTarget } from "../components/forms/CorrectionDialog";
import { LinkOwnerDialog } from "../components/forms/LinkOwnerDialog";
import { ManualEntryDialog, type ManualEntryPrefill } from "../components/forms/ManualEntryDialog";
import { RegisterVehicleDialog } from "../components/forms/RegisterVehicleDialog";
import { SimulatePlateDialog } from "../components/forms/SimulatePlateDialog";
import { Button } from "../components/ui/Button";
import { Dialog as ModalDialog } from "../components/ui/Dialog";
import { EmptyState, Skeleton } from "../components/ui/Feedback";
import { SearchInput } from "../components/ui/Form";
import { FilterChips, PageHeader, Section, StatTile } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { useFeed } from "../feed/LiveFeedContext";
import { cx } from "../lib/cx";
import { compactNumber, gateLabel } from "../lib/format";
import { normalizePlate } from "../app/nav";

type Dialog =
  | { type: "register"; plate: string }
  | { type: "link"; plate: string; personType?: PersonType; reference?: string }
  | { type: "manual"; prefill: ManualEntryPrefill }
  | { type: "correct"; target: CorrectionTarget }
  | { type: "simulate" }
  | { type: "camera"; gateId: string }
  | null;

/** The slides' filter chips; "Linked" includes inactive registrations, "No plate" shows only when present. */
type StatusChip = "ALL" | "LINKED" | "UNLINKED" | "REVIEW" | "NO_PLATE";
const CHIP_OF: Record<LinkStatus, StatusChip> = {
  LINKED: "LINKED",
  LINKED_INACTIVE: "LINKED",
  NOT_LINKED: "UNLINKED",
  LOW_CONFIDENCE: "REVIEW",
  NO_PLATE: "NO_PLATE",
};
const CHIP_LABEL: Record<StatusChip, string> = { ALL: "All", LINKED: "Linked", UNLINKED: "Unlinked", REVIEW: "Review", NO_PLATE: "No plate" };
// Older links (#/feed?status=LOW_CONFIDENCE) keep working.
function parseChip(value: string | null): StatusChip {
  if (!value) return "ALL";
  if (value in CHIP_LABEL) return value as StatusChip;
  return CHIP_OF[value as LinkStatus] ?? "ALL";
}

// Cards rendered at a time: the feed holds up to 200, each with a snapshot request.
const PAGE = 24;
const LIST_PAGE = 40;

export function FeedPage() {
  const { token, user } = useSession();
  const { cards, connection, lastSyncAt, upsertItem } = useFeed();
  const notify = useToast();
  const gatesQuery = useGates();
  const { data: streamSettings } = useStreamSettings(5000);
  const [params, setParams] = useSearchParams();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [plateFilter, setPlateFilter] = useState(params.get("plate") ?? "");
  const [shown, setShown] = useState(PAGE);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const since = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
  }, []);
  const summary = useDashboard(since);

  const statusFilter = parseChip(params.get("status"));
  const gateFilter = params.get("gate") ?? "ALL";
  const view = params.get("view") === "cards" ? "cards" : "console";
  const setParam = (key: string, value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value === "ALL" || value === "" || (key === "view" && value === "console")) next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );

  // All gates / Gate 1 / Gate 2 / Gate 3: the numbered campus gates plus any gate seen in the feed.
  const gates = useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of gatesQuery.data ?? []) if (g.status !== "INACTIVE" && /^GATE_\d+$/i.test(g.id)) seen.set(g.id, gateLabel(g));
    for (const c of cards) if (!seen.has(c.item.observation.gate.id)) seen.set(c.item.observation.gate.id, gateLabel(c.item.observation.gate));
    return [...seen.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [cards, gatesQuery.data]);

  const needle = normalizePlate(plateFilter);
  const scoped = cards.filter((c) => gateFilter === "ALL" || c.item.observation.gate.id === gateFilter);
  const visible = scoped.filter(
    (c) => (statusFilter === "ALL" || CHIP_OF[c.item.link_status] === statusFilter) && (!needle || (c.item.observation.plate.normalized ?? "").includes(needle)),
  );

  const counts = useMemo(() => {
    const out: Record<StatusChip, number> = { ALL: scoped.length, LINKED: 0, UNLINKED: 0, REVIEW: 0, NO_PLATE: 0 };
    for (const c of scoped) out[CHIP_OF[c.item.link_status]]++;
    return out;
  }, [scoped]);
  const toReview = scoped.filter((c) => c.item.link_status === "LOW_CONFIDENCE" && !c.item.resolution).length;

  useEffect(() => setShown(view === "cards" ? PAGE : LIST_PAGE), [statusFilter, gateFilter, needle, view]);

  const selected = visible.find((c) => c.item.observation.id === selectedId) ?? visible[0] ?? null;

  const select = (id: string) => {
    setSelectedId(id);
    // Phones stack the panel under the list: bring it into view.
    if (window.innerWidth < 1024) window.setTimeout(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  const closeDialog = useCallback(() => setDialog(null), []);
  const onResolved = useCallback((item: ResolvedObservation) => upsertItem(item, "RESOLUTION_ADDED"), [upsertItem]);
  const s = summary.data;
  const chips: StatusChip[] = ["ALL", "LINKED", "UNLINKED", "REVIEW", ...(counts.NO_PLATE > 0 || statusFilter === "NO_PLATE" ? (["NO_PLATE"] as StatusChip[]) : [])];

  return (
    <>
      <PageHeader
        title="Live plate feed"
        description="Plates read at every gate as they arrive, matched against the registry. The software never moves a barrier; you decide at the gate."
        actions={
          <>
            {streamSettings && streamSettings.active_gates_count > 0 && (
              <button
                type="button"
                onClick={() => {
                  const running = streamSettings.gates.find((g) => g.is_running || g.enabled);
                  if (running) setDialog({ type: "camera", gateId: running.gate_id });
                }}
                className="hidden items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 sm:inline-flex cursor-pointer transition-colors"
                title={`Click to view live camera stream snapshot (${streamSettings.total_fps_budget} FPS budget)`}
              >
                <Camera className="h-3.5 w-3.5 text-sky-600 dark:text-sky-400" />
                <span>
                  {streamSettings.active_gates_count} Gate{streamSettings.active_gates_count === 1 ? "" : "s"} · {streamSettings.per_gate_target_fps.toFixed(1)} FPS
                </span>
              </button>
            )}
            <ConnectionIndicator state={connection} lastSyncAt={lastSyncAt} />
            {user.role === "ADMIN" && (
              <Button icon={<FlaskConical className="h-4 w-4" />} onClick={() => setDialog({ type: "simulate" })}>
                Simulate a plate
              </Button>
            )}
            <Button variant="primary" className="hidden sm:inline-flex" icon={<Plus className="h-4 w-4" />} onClick={() => setDialog({ type: "manual", prefill: {} })}>
              Add vehicle entry
            </Button>
          </>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatTile
          label="Vehicles on campus"
          value={s ? compactNumber(s.presence.inside) : "—"}
          sub={s ? `${s.presence.inside_linked} linked · ${s.presence.inside_unlinked} unlinked` : undefined}
          icon={<Building2 className="h-4 w-4" />}
          to="/inside"
          loading={summary.isLoading}
        />
        <StatTile label="Unlinked plates" value={compactNumber(counts.UNLINKED)} sub="in the live feed" icon={<Unlink className="h-4 w-4" />} to="/feed?status=UNLINKED" />
        <StatTile label="Plates to review" value={compactNumber(toReview)} sub="close matches, unconfirmed" icon={<AlertCircle className="h-4 w-4" />} to="/feed?status=REVIEW" />
        <StatTile
          label="Delivery flags"
          value={s?.delivery_flags !== undefined ? compactNumber(s.delivery_flags) : "—"}
          sub="REVIEW / ALERT awaiting a guard"
          icon={<Package className="h-4 w-4" />}
          to="/deliveries?decision=OPEN"
          loading={summary.isLoading}
        />
      </div>

      <div className="mb-4 space-y-3">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
          <FilterChips<string>
            label="Gate"
            value={gateFilter}
            onChange={(v) => setParam("gate", v)}
            options={[{ value: "ALL", label: "All gates" }, ...gates.map(([id, label]) => ({ value: id, label }))]}
          />
          <div className="flex gap-2 lg:ml-auto">
            <SearchInput label="Filter by plate" placeholder="Filter by plate" value={plateFilter} onChange={setPlateFilter} className="flex-1 sm:w-56" mono />
            <div className="flex rounded-lg ring-1 ring-inset ring-slate-300 dark:ring-slate-700" role="group" aria-label="View">
              {(["console", "cards"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={view === v}
                  title={v === "console" ? "List and detail" : "Cards"}
                  onClick={() => setParam("view", v)}
                  className={cx(
                    "flex items-center px-2.5 first:rounded-l-lg last:rounded-r-lg",
                    view === v ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white",
                  )}
                >
                  {v === "console" ? <List className="h-4 w-4" aria-hidden /> : <LayoutGrid className="h-4 w-4" aria-hidden />}
                  <span className="sr-only">{v === "console" ? "List and detail" : "Cards"}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
        <FilterChips<StatusChip>
          label="Registry linkage"
          value={statusFilter}
          onChange={(v) => setParam("status", v)}
          options={chips.map((c) => ({ value: c, label: CHIP_LABEL[c], count: counts[c] }))}
        />
      </div>

      {connection === "connecting" && cards.length === 0 ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-56 rounded-xl" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<Radio className="h-5 w-5" />}
            title={cards.length === 0 ? "No plates read yet" : "Nothing matches these filters"}
            description={cards.length === 0 ? "New camera reads appear here as they arrive. Guards can also add a vehicle entry by hand." : "Clear a filter to see more reads."}
          />
        </div>
      ) : view === "cards" ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {visible.slice(0, shown).map((card) => (
            <ObservationCard
              key={card.item.observation.id}
              token={token}
              card={card}
              onRegister={(plate) => setDialog({ type: "register", plate })}
              onLink={(plate) => setDialog({ type: "link", plate })}
              onManualEntry={(prefill) => setDialog({ type: "manual", prefill })}
              onCorrect={(target) => setDialog({ type: "correct", target })}
              onResolved={onResolved}
            />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <Section
            className="lg:col-span-2"
            title={
              <span className="flex items-center gap-2">
                Plates read
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  <span className={cx("h-1.5 w-1.5 rounded-full", connection === "live" ? "animate-pulse bg-sky-500" : "bg-slate-400")} aria-hidden />
                  {connection === "live" ? "Live" : connection}
                </span>
              </span>
            }
            description={`${visible.length} read${visible.length === 1 ? "" : "s"}${gateFilter === "ALL" ? " across all gates" : ""}`}
            bodyClassName="p-0"
          >
            <ul className="divide-y divide-slate-100 dark:divide-slate-800 lg:max-h-[calc(100dvh-22rem)] lg:min-h-[24rem] lg:overflow-y-auto">
              {visible.slice(0, shown).map((card) => (
                <PlateRow key={card.item.observation.id} card={card} selected={selected?.item.observation.id === card.item.observation.id} onSelect={() => select(card.item.observation.id)} />
              ))}
              {visible.length > shown && (
                <li className="p-3 text-center">
                  <Button size="sm" onClick={() => setShown((n) => n + LIST_PAGE)}>
                    Show {Math.min(LIST_PAGE, visible.length - shown)} more
                  </Button>
                </li>
              )}
            </ul>
          </Section>
          <div ref={detailRef} className="scroll-mt-20 lg:col-span-3">
            <Section title="Plate detail">
              {selected ? (
                <PlateDetailPanel
                  key={selected.item.observation.id}
                  token={token}
                  item={selected.item}
                  onResolved={onResolved}
                  onLink={(plate, personType, reference) => setDialog({ type: "link", plate, personType, reference })}
                  onMarkVisitor={(plate) => setDialog({ type: "register", plate })}
                  onManualEntry={(prefill) => setDialog({ type: "manual", prefill })}
                  onCorrect={(target) => setDialog({ type: "correct", target })}
                />
              ) : (
                <EmptyState title="Select a plate" />
              )}
            </Section>
          </div>
        </div>
      )}
      {view === "cards" && visible.length > shown && (
        <div className="mt-4 flex justify-center">
          <Button onClick={() => setShown((n) => n + PAGE)}>
            Show {Math.min(PAGE, visible.length - shown)} more · {visible.length - shown} not shown
          </Button>
        </div>
      )}

      <div className="mt-6">
        <DeliveryScreeningPanel token={token} />
      </div>

      {/* Phone: the primary guard action stays within thumb reach */}
      <button
        type="button"
        onClick={() => setDialog({ type: "manual", prefill: {} })}
        className="fixed bottom-[calc(5rem+env(safe-area-inset-bottom))] right-4 z-20 inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-3.5 text-sm font-semibold text-white shadow-lg shadow-slate-900/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2 dark:bg-slate-100 dark:text-slate-900 sm:hidden"
      >
        <Plus className="h-4 w-4" aria-hidden />
        Add vehicle entry
      </button>

      {dialog?.type === "register" && (
        <RegisterVehicleDialog
          token={token}
          role={user.role}
          plate={dialog.plate}
          onClose={closeDialog}
          onRegistered={(message) => {
            setDialog(null);
            notify(message);
          }}
        />
      )}
      {dialog?.type === "link" && (
        <LinkOwnerDialog
          token={token}
          role={user.role}
          plate={dialog.plate}
          initialPersonType={dialog.personType}
          initialReference={dialog.reference}
          onClose={closeDialog}
          onLinked={(message) => {
            setDialog(null);
            notify(message);
          }}
        />
      )}
      {dialog?.type === "manual" && (
        <ManualEntryDialog
          token={token}
          prefill={dialog.prefill}
          onClose={closeDialog}
          onLogged={(item) => {
            upsertItem(item, "OBSERVATION_CREATED");
            setSelectedId(item.observation.id);
            setDialog(null);
            notify(`Vehicle entry logged for ${item.observation.plate.normalized}.`);
          }}
        />
      )}
      {dialog?.type === "correct" && (
        <CorrectionDialog
          token={token}
          target={dialog.target}
          onClose={closeDialog}
          onCorrected={() => {
            setDialog(null);
            notify("Correction recorded.");
          }}
        />
      )}
      {dialog?.type === "simulate" && (
        <SimulatePlateDialog
          token={token}
          onClose={closeDialog}
          onSent={(plate) => {
            setDialog(null);
            setSelectedId(null);
            notify(`Simulated read ${plate} sent; it appears in the feed in a moment.`);
          }}
        />
      )}
      {dialog?.type === "camera" && (
        <FeedCameraDialog
          token={token}
          gateId={dialog.gateId}
          onClose={closeDialog}
        />
      )}
    </>
  );
}

function FeedCameraDialog({
  token,
  gateId,
  onClose,
}: {
  token: string;
  gateId: string;
  onClose: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(Date.now());

  useEffect(() => {
    let objectUrl: string | null = null;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .gateLiveFrame(token, gateId, controller.signal)
      .then(({ blob, status }) => {
        if (!blob) {
          setError(`Could not grab snapshot from ${gateId} (HTTP ${status}). Stream may be idle.`);
          setLoading(false);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
        setLoading(false);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "Failed to load snapshot");
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, gateId, refreshKey]);

  return (
    <ModalDialog
      title={`Live Camera Stream · ${gateId}`}
      description="Live snapshot grabbed directly from the gate's camera feed"
      onClose={onClose}
      size="xl"
      footer={
        <div className="flex w-full items-center justify-between">
          <Button
            variant="secondary"
            size="sm"
            icon={<Camera className="h-3.5 w-3.5" />}
            onClick={() => setRefreshKey(Date.now())}
          >
            Refresh Snapshot
          </Button>
          <Button variant="primary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="flex min-h-[300px] flex-col items-center justify-center rounded-lg bg-slate-950 p-2">
        {loading && !url && (
          <div className="flex flex-col items-center gap-2 py-12 text-slate-400">
            <Camera className="h-8 w-8 animate-pulse text-sky-400" />
            <span className="text-xs">Capturing snapshot from live stream...</span>
          </div>
        )}
        {error && (
          <div className="flex flex-col items-center gap-2 py-8 text-rose-400">
            <AlertCircle className="h-6 w-6" />
            <span className="max-w-sm text-center text-xs">{error}</span>
          </div>
        )}
        {url && (
          <img
            src={url}
            alt={`Live stream from ${gateId}`}
            className="max-h-[68vh] w-auto rounded-md object-contain shadow-lg"
          />
        )}
      </div>
    </ModalDialog>
  );
}
