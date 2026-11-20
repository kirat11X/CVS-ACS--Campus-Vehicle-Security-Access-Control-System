import { AlertCircle, Building2, Camera, Check, Download, FlaskConical, LayoutGrid, List, Package, Pause, Play, Plus, Radio, Unlink, Video } from "lucide-react";
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
            <Button
              variant="secondary"
              icon={<Video className="h-4 w-4 text-sky-500 animate-pulse" />}
              onClick={() => {
                const running = streamSettings?.gates.find((g) => g.is_running || g.enabled);
                setDialog({ type: "camera", gateId: running?.gate_id || "GATE_1" });
              }}
              title="Open Live Camera Stream & Capture Snapshots"
            >
              Live Camera Feed
            </Button>
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
  gateId: initialGateId,
  onClose,
}: {
  token: string;
  gateId: string;
  onClose: () => void;
}) {
  const [activeGate, setActiveGate] = useState(initialGateId || "GATE_1");
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(true);
  const [frameCount, setFrameCount] = useState(0);

  // Snapshot Storage State
  const [storingSnapshot, setStoringSnapshot] = useState(false);
  const [storedSnapshot, setStoredSnapshot] = useState<{
    filename: string;
    path: string;
    timestamp: string;
  } | null>(null);

  // Continuous Live Stream frame loop
  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    let timer: number | null = null;

    const fetchFrame = async () => {
      if (!active || !isLive) return;
      try {
        const { blob, status } = await api.gateLiveFrame(token, activeGate);
        if (!active) return;
        if (blob) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
          setLoading(false);
          setError(null);
          setFrameCount((c) => c + 1);
        } else if (status !== 200) {
          setError(`Camera stream offline or idle at ${activeGate} (HTTP ${status})`);
          setLoading(false);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Live stream dropped");
          setLoading(false);
        }
      }
      if (active && isLive) {
        timer = window.setTimeout(fetchFrame, 350); // ~3 FPS smooth preview
      }
    };

    setLoading(true);
    setError(null);
    void fetchFrame();

    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, activeGate, isLive]);

  const handleTakeSnapshot = async () => {
    setStoringSnapshot(true);
    setStoredSnapshot(null);
    try {
      const res = await api.captureGateSnapshot(token, activeGate);
      if (res && res.success) {
        setStoredSnapshot({
          filename: res.filename,
          path: res.path,
          timestamp: res.timestamp,
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to store snapshot");
    } finally {
      setStoringSnapshot(false);
    }
  };

  return (
    <ModalDialog
      title={`Live Camera Feed & Snapshot Recorder · ${activeGate}`}
      description="Real-time optical camera stream from campus perimeter access gate with permanent RL dataset snapshot storage."
      onClose={onClose}
      size="xl"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Button
              variant={isLive ? "secondary" : "primary"}
              size="sm"
              icon={isLive ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              onClick={() => setIsLive((v) => !v)}
            >
              {isLive ? "Pause Stream" : "Resume Live Stream"}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Camera className="h-3.5 w-3.5" />}
              loading={storingSnapshot}
              onClick={handleTakeSnapshot}
              title="Capture and permanently store this frame for active learning / RL"
            >
              📸 Take Snapshot & Store
            </Button>
          </div>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        {/* Gate Switcher & Stream Controls */}
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-100 p-2 dark:bg-slate-800">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-400">Select Gate:</span>
            {["GATE_1", "GATE_2", "GATE_3"].map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => {
                  setActiveGate(g);
                  setUrl(null);
                  setStoredSnapshot(null);
                }}
                className={`rounded px-2.5 py-1 text-xs font-bold transition-all cursor-pointer ${
                  activeGate === g
                    ? "bg-sky-600 text-white shadow-sm"
                    : "bg-white text-slate-700 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-700"
                }`}
              >
                {g.replace("_", " ")}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            {isLive ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-bold text-emerald-700 ring-1 ring-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-400 dark:ring-emerald-800">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
                ● LIVE FEED (Frame #{frameCount})
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-bold text-amber-700 ring-1 ring-amber-300 dark:bg-amber-950/40 dark:text-amber-400">
                ❚❚ PAUSED
              </span>
            )}
          </div>
        </div>

        {/* Snapshot Confirmation Alert Banner */}
        {storedSnapshot && (
          <div className="flex items-center justify-between rounded-lg border border-emerald-300 bg-emerald-50 p-2.5 text-xs text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
            <div className="flex items-center gap-2">
              <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              <div>
                <strong>Snapshot Stored:</strong> {storedSnapshot.filename}
                <div className="text-[11px] text-emerald-700 dark:text-emerald-300">
                  Permanently saved to disk (<code className="font-mono">media/snapshots/</code> & <code className="font-mono">data/rl_dataset/</code>)
                </div>
              </div>
            </div>
            <a
              href={storedSnapshot.path}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white shadow hover:bg-emerald-700"
            >
              <Download className="h-3 w-3" />
              View / Download
            </a>
          </div>
        )}

        {/* Video Canvas Container */}
        <div className="relative flex min-h-[340px] flex-col items-center justify-center overflow-hidden rounded-xl bg-slate-950 p-2 shadow-inner ring-1 ring-slate-800">
          {loading && !url && (
            <div className="flex flex-col items-center gap-2 py-16 text-slate-400">
              <Video className="h-10 w-10 animate-pulse text-sky-400" />
              <span className="text-xs font-medium">Connecting to {activeGate} live video pipeline...</span>
            </div>
          )}
          {error && !url && (
            <div className="flex flex-col items-center gap-2 py-12 text-rose-400">
              <AlertCircle className="h-8 w-8" />
              <span className="max-w-md text-center text-xs font-semibold">{error}</span>
              <p className="text-[11px] text-slate-400">The RTSP/HTTP camera stream runner may be initializing or in idle standby.</p>
            </div>
          )}
          {url && (
            <div className="relative">
              <img
                src={url}
                alt={`Live stream from ${activeGate}`}
                className="max-h-[65vh] w-auto rounded-lg object-contain shadow-2xl"
              />
              <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-slate-950/80 px-2.5 py-1 font-mono text-xs font-bold text-white shadow">
                {activeGate} · LIVE ANPR ACTIVE
              </div>
            </div>
          )}
        </div>
      </div>
    </ModalDialog>
  );
}
