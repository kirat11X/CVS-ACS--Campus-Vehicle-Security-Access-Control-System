import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  KeyRound,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { ApiError, api } from "../api/client";
import { useAlerts, useInvalidate } from "../api/queries";
import type { ResolvedObservation } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { ConnectionIndicator } from "../components/feed/ConnectionIndicator";
import { SnapshotImage } from "../components/feed/SnapshotImage";
import {
  ReasonCodeBadge,
  StandardReasonCode,
  determineReasonCode,
} from "../components/ReasonCodeBadge";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import {
  Badge,
  EmptyState,
  ErrorNote,
} from "../components/ui/Feedback";
import { FilterChips, PageHeader } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { useFeed } from "../feed/LiveFeedContext";
import { cx } from "../lib/cx";
import {
  formatDateTime,
  formatPercent,
  formatRelative,
  humanize,
} from "../lib/format";
import { useNow } from "../lib/hooks";
import type { TriageAuditRecord, TriageCategoryFilter } from "../types";

export function SecurityReviewPage() {
  const { token, user } = useSession();
  const notify = useToast();
  const invalidate = useInvalidate();
  const now = useNow(30_000);
  const { cards, connection, lastSyncAt, upsertItem } = useFeed();
  const alertsQuery = useAlerts(100, 30_000);

  // Local storage of triage decisions for audit during shift
  const [auditLog, setAuditLog] = useState<Record<string, TriageAuditRecord>>({});
  const [filter, setFilter] = useState<TriageCategoryFilter>("ALL");
  const [search, setSearch] = useState("");
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ id: string; msg: string } | null>(null);

  // Mandatory Reason Notes Override Modal state
  const [overrideTarget, setOverrideTarget] = useState<ResolvedObservation | null>(null);
  const [overrideReason, setOverrideReason] = useState("");

  // Process live feed cards to find items requiring human-in-the-loop triage
  const triageCandidates = useMemo(() => {
    return cards.map((c) => {
      const item = c.item;
      const obs = item.observation;
      const conf = obs.plate.confidence;
      const isLowConfidence =
        item.link_status === "LOW_CONFIDENCE" ||
        (conf !== null && conf !== undefined && conf < 0.7);

      const isUnknown =
        item.link_status === "NOT_LINKED" ||
        item.link_status === "NO_PLATE" ||
        !item.vehicle ||
        item.vehicle.category === "UNKNOWN";

      const isUnapprovedVisitor =
        item.vehicle?.category === "VISITOR" &&
        (!item.owner || item.flags.includes("VISITOR_UNAPPROVED") || !item.vehicle.valid_from);

      const isPolicyAlert =
        item.flags.includes("BLACKLISTED") ||
        item.vehicle?.registry_status === "BLACKLISTED" ||
        item.flags.includes("ALERT_RESTRICTED_ITEM") ||
        item.flags.includes("VALIDITY_ENDED") ||
        item.flags.includes("VALIDITY_NOT_STARTED");

      const needsTriage =
        isLowConfidence || isUnknown || isUnapprovedVisitor || isPolicyAlert;

      const reasonCode = determineReasonCode({
        plateConfidence: conf,
        linkStatus: item.link_status,
        vehicle: item.vehicle,
        flags: item.flags,
      });

      return {
        item,
        card: c,
        isLowConfidence,
        isUnknown,
        isUnapprovedVisitor,
        isPolicyAlert,
        needsTriage,
        reasonCode,
      };
    });
  }, [cards]);

  // Filter candidates based on category chip
  const filteredCandidates = useMemo(() => {
    const q = search.trim().toUpperCase();

    return triageCandidates.filter((cand) => {
      // Must be an item that requires triage or has already been triaged in this session
      const audit = auditLog[cand.item.observation.id];
      if (!cand.needsTriage && !audit) return false;

      // Search match
      if (q) {
        const plate = cand.item.observation.plate.normalized ?? "";
        const raw = cand.item.observation.plate.raw ?? "";
        const gate = cand.item.observation.gate.name.toUpperCase();
        if (!plate.includes(q) && !raw.toUpperCase().includes(q) && !gate.includes(q)) {
          return false;
        }
      }

      if (filter === "ALL") return true;
      if (filter === "LOW_CONFIDENCE") return cand.isLowConfidence;
      if (filter === "UNKNOWN_VEHICLE") return cand.isUnknown;
      if (filter === "UNAPPROVED_VISITOR") return cand.isUnapprovedVisitor;
      if (filter === "POLICY_ALERT") return cand.isPolicyAlert;
      return true;
    });
  }, [triageCandidates, auditLog, filter, search]);

  // Counts for triage categories
  const counts = useMemo(() => {
    let lowConf = 0;
    let unknown = 0;
    let visitor = 0;
    let alertCount = 0;
    let totalPending = 0;

    for (const c of triageCandidates) {
      if (!c.needsTriage) continue;
      const isTriaged = !!auditLog[c.item.observation.id];
      if (!isTriaged) totalPending++;
      if (c.isLowConfidence) lowConf++;
      if (c.isUnknown) unknown++;
      if (c.isUnapprovedVisitor) visitor++;
      if (c.isPolicyAlert) alertCount++;
    }

    return {
      total: totalPending,
      lowConf,
      unknown,
      visitor,
      alertCount,
      handledCount: Object.keys(auditLog).length,
    };
  }, [triageCandidates, auditLog]);

  // Triage Action Handlers
  const handleAllow = async (item: ResolvedObservation, code: StandardReasonCode) => {
    const obsId = item.observation.id;
    setPendingActionId(obsId);
    setActionError(null);

    try {
      // Confirm resolution if suggestions exist or confirm movement
      if (item.suggestions.length > 0 && !item.resolution) {
        const res = await api.recordResolution(token, {
          observation_id: obsId,
          chosen_vehicle_id: item.suggestions[0]?.vehicle_id ?? "none",
          note: `Guard Triage ALLOW: ${code}`,
        });
        upsertItem(res.item, "RESOLUTION_ADDED");
      }

      // Record audit record
      const record: TriageAuditRecord = {
        id: `triage_${Date.now()}`,
        eventId: obsId,
        action: "ALLOW",
        reasonCode: code,
        guardName: user.full_name,
        notes: "Guard approved entry via Human-In-The-Loop review.",
        timestamp: new Date().toISOString(),
      };

      setAuditLog((prev) => ({ ...prev, [obsId]: record }));
      notify(`Plate ${item.observation.plate.normalized || "Vehicle"}: Allowed entry.`);
      void invalidate("dashboard", "alerts");
    } catch (e) {
      setActionError({
        id: obsId,
        msg: e instanceof ApiError ? e.message : "Failed to record ALLOW decision.",
      });
    } finally {
      setPendingActionId(null);
    }
  };

  const handleDeny = async (item: ResolvedObservation, code: StandardReasonCode) => {
    const obsId = item.observation.id;
    setPendingActionId(obsId);
    setActionError(null);

    try {
      const record: TriageAuditRecord = {
        id: `triage_${Date.now()}`,
        eventId: obsId,
        action: "DENY",
        reasonCode: code,
        guardName: user.full_name,
        notes: "Gate entry refused by security guard.",
        timestamp: new Date().toISOString(),
      };

      setAuditLog((prev) => ({ ...prev, [obsId]: record }));
      notify(`Plate ${item.observation.plate.normalized || "Vehicle"}: Entry Denied.`);
      void invalidate("dashboard", "alerts");
    } catch (e) {
      setActionError({
        id: obsId,
        msg: e instanceof ApiError ? e.message : "Failed to record DENY decision.",
      });
    } finally {
      setPendingActionId(null);
    }
  };

  const handleOpenOverrideModal = (item: ResolvedObservation) => {
    setOverrideTarget(item);
    setOverrideReason("");
  };

  const handleConfirmOverride = async () => {
    if (!overrideTarget || !overrideReason.trim()) return;
    const obsId = overrideTarget.observation.id;
    setPendingActionId(obsId);

    try {
      const record: TriageAuditRecord = {
        id: `triage_${Date.now()}`,
        eventId: obsId,
        action: "OVERRIDE",
        reasonCode: "ALLOW_REGISTERED_VEHICLE",
        guardName: user.full_name,
        notes: overrideReason.trim(),
        timestamp: new Date().toISOString(),
      };

      setAuditLog((prev) => ({ ...prev, [obsId]: record }));
      notify(
        `Plate ${overrideTarget.observation.plate.normalized || "Vehicle"}: Override logged and access permitted.`,
      );
      setOverrideTarget(null);
      setOverrideReason("");
      void invalidate("dashboard", "alerts");
    } catch {
      notify("Failed to record override action.", "info");
    } finally {
      setPendingActionId(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            <ShieldAlert className="h-6 w-6 text-amber-600 dark:text-amber-400" />
            <span>Security Review Queue & Triage</span>
          </span>
        }
        description="Human-in-the-loop security queue for low-confidence reads (< 0.70), unregistered vehicles, unapproved visitors, and policy alerts."
        actions={
          <div className="flex items-center gap-2">
            <ConnectionIndicator state={connection} lastSyncAt={lastSyncAt} />
            <Button
              size="sm"
              variant="ghost"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => void alertsQuery.refetch()}
            >
              Sync
            </Button>
          </div>
        }
      />

      {/* KPI Triage Dashboard Counters */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Pending Triage
          </div>
          <div className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">
            {counts.total}
          </div>
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3.5 dark:border-amber-800/50 dark:bg-amber-950/20">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-800 dark:text-amber-300">
            Low Conf (&lt; 0.70)
          </div>
          <div className="mt-1 text-2xl font-bold text-amber-900 dark:text-amber-200">
            {counts.lowConf}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 dark:border-slate-800 dark:bg-slate-800/40">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400">
            Unknown Vehicles
          </div>
          <div className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">
            {counts.unknown}
          </div>
        </div>

        <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3.5 dark:border-rose-800/50 dark:bg-rose-950/20">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-800 dark:text-rose-300">
            Policy Alerts
          </div>
          <div className="mt-1 text-2xl font-bold text-rose-900 dark:text-rose-200">
            {counts.alertCount}
          </div>
        </div>

        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5 dark:border-emerald-800/50 dark:bg-emerald-950/20">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800 dark:text-emerald-300">
            Handled This Shift
          </div>
          <div className="mt-1 text-2xl font-bold text-emerald-900 dark:text-emerald-200">
            {counts.handledCount}
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:max-w-xs">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by plate, gate, or raw OCR..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-xs placeholder:text-slate-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
          </div>
        </div>

        <FilterChips<TriageCategoryFilter>
          label="Triage Queue Filters"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "ALL", label: `All Queue (${counts.total})` },
            { value: "LOW_CONFIDENCE", label: `Low Confidence (${counts.lowConf})` },
            { value: "UNKNOWN_VEHICLE", label: `Unknown Vehicles (${counts.unknown})` },
            { value: "UNAPPROVED_VISITOR", label: `Visitors (${counts.visitor})` },
            { value: "POLICY_ALERT", label: `Alerts (${counts.alertCount})` },
          ]}
        />
      </div>

      {/* Main Review Queue Feed */}
      <div className="space-y-4">
        {filteredCandidates.length === 0 ? (
          <div className="card p-8">
            <EmptyState
              icon={<ShieldCheck className="h-8 w-8 text-emerald-500" />}
              title="Security Queue is Clear"
              description="No vehicle sightings or gate events currently require human-in-the-loop review. Incoming low-confidence or unregistered vehicle events will appear live."
            />
          </div>
        ) : (
          filteredCandidates.map(({ item, reasonCode, isLowConfidence }) => {
            const obs = item.observation;
            const plate = obs.plate.normalized;
            const audit = auditLog[obs.id];
            const isActing = pendingActionId === obs.id;
            const err = actionError?.id === obs.id ? actionError.msg : null;

            return (
              <div
                key={obs.id}
                className={cx(
                  "card overflow-hidden border-l-4 p-5 transition-all",
                  audit
                    ? "border-l-slate-400 opacity-80 dark:border-l-slate-600"
                    : isLowConfidence
                      ? "border-l-amber-500 bg-amber-50/20 dark:border-l-amber-500 dark:bg-amber-950/10"
                      : "border-l-rose-500 bg-rose-50/10 dark:border-l-rose-500 dark:bg-rose-950/10",
                )}
              >
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  {/* Left: Snapshot + Vehicle & Plate Details */}
                  <div className="flex gap-4">
                    <SnapshotImage
                      token={token}
                      observation={obs}
                      className="h-28 w-40 shrink-0 rounded-lg ring-1 ring-slate-200 dark:ring-slate-700"
                    />

                    <div className="space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        {plate ? (
                          <Link
                            to={`/vehicles/${encodeURIComponent(plate)}`}
                            className="plate text-2xl font-bold text-slate-900 underline-offset-4 hover:underline dark:text-white"
                          >
                            {plate}
                          </Link>
                        ) : (
                          <span className="plate text-2xl font-bold text-slate-400">
                            — — —
                          </span>
                        )}

                        <ReasonCodeBadge code={reasonCode} />

                        {isLowConfidence && (
                          <Badge className="bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                            Confidence: {formatPercent(obs.plate.confidence)}
                          </Badge>
                        )}
                      </div>

                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {obs.plate.raw ? (
                          <>
                            Raw OCR:{" "}
                            <span className="font-mono font-semibold text-slate-700 dark:text-slate-200">
                              “{obs.plate.raw}”
                            </span>{" "}
                            ·{" "}
                          </>
                        ) : null}
                        Gate:{" "}
                        <strong className="text-slate-700 dark:text-slate-300">
                          {obs.gate.name}
                        </strong>{" "}
                        · Direction: {humanize(obs.direction)} · Observed:{" "}
                        {formatDateTime(obs.observed_at)} (
                        {formatRelative(obs.observed_at, now)})
                      </p>

                      {/* Registry status or owner context */}
                      <div className="text-xs text-slate-600 dark:text-slate-400">
                        {item.vehicle ? (
                          <span>
                            Registered: {humanize(item.vehicle.category)} (
                            {item.vehicle.registry_status})
                            {item.owner ? ` · Owner: ${item.owner.name} (${item.owner.institutional_id})` : ""}
                          </span>
                        ) : (
                          <span className="font-medium text-amber-700 dark:text-amber-300">
                            Unregistered vehicle · No owner or campus permit on record
                          </span>
                        )}
                      </div>

                      {/* Matching suggestions if fuzzy match was computed */}
                      {item.suggestions.length > 0 && !audit && (
                        <div className="mt-2 rounded bg-white/70 p-2 text-xs ring-1 ring-slate-200 dark:bg-slate-800/60 dark:ring-slate-700">
                          <span className="font-semibold text-slate-700 dark:text-slate-300">
                            Suggested Match:
                          </span>{" "}
                          <span className="font-mono font-bold text-sky-600 dark:text-sky-400">
                            {item.suggestions[0]?.plate}
                          </span>{" "}
                          ({formatPercent(item.suggestions[0]?.similarity)} similar
                          to {item.suggestions[0]?.owner_name || "campus owner"})
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Right: Guard Triage Controls or Audit Badge */}
                  <div className="shrink-0 lg:w-72">
                    {audit ? (
                      /* Audit Trail Display for Triaged Items */
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 dark:border-slate-800 dark:bg-slate-900">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                            Triaged Audit Record
                          </span>
                          <span
                            className={cx(
                              "rounded-full px-2 py-0.5 text-[11px] font-bold",
                              audit.action === "ALLOW"
                                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
                                : audit.action === "DENY"
                                  ? "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-200"
                                  : "bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-200",
                            )}
                          >
                            {audit.action}
                          </span>
                        </div>

                        <div className="mt-2 text-xs text-slate-700 dark:text-slate-300">
                          <strong>{audit.guardName}</strong>
                          <p className="mt-0.5 italic text-slate-500 dark:text-slate-400">
                            “{audit.notes || "No notes"}”
                          </p>
                        </div>

                        <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-slate-400">
                          <span>{formatDateTime(audit.timestamp)}</span>
                          <ReasonCodeBadge code={audit.reasonCode} compact />
                        </div>
                      </div>
                    ) : (
                      /* Live Action Triage Controls: ALLOW, DENY, OVERRIDE */
                      <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
                        <div className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                          Guard Triage Actions
                        </div>

                        {err && <ErrorNote message={err} />}

                        <div className="grid grid-cols-3 gap-2">
                          <Button
                            size="sm"
                            variant="primary"
                            className="bg-emerald-600 hover:bg-emerald-700 dark:bg-emerald-600"
                            icon={<CheckCircle2 className="h-3.5 w-3.5" />}
                            loading={isActing}
                            disabled={isActing}
                            onClick={() => handleAllow(item, reasonCode)}
                          >
                            ALLOW
                          </Button>

                          <Button
                            size="sm"
                            className="border-rose-300 bg-rose-50 text-rose-800 hover:bg-rose-100 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
                            icon={<Ban className="h-3.5 w-3.5 text-rose-600" />}
                            loading={isActing}
                            disabled={isActing}
                            onClick={() => handleDeny(item, reasonCode)}
                          >
                            DENY
                          </Button>

                          <Button
                            size="sm"
                            className="border-purple-300 bg-purple-50 text-purple-800 hover:bg-purple-100 dark:border-purple-800 dark:bg-purple-950/40 dark:text-purple-300"
                            icon={<KeyRound className="h-3.5 w-3.5 text-purple-600" />}
                            loading={isActing}
                            disabled={isActing}
                            onClick={() => handleOpenOverrideModal(item)}
                          >
                            OVERRIDE
                          </Button>
                        </div>

                        <p className="text-[10px] text-slate-400">
                          Override requires mandatory justification for audit logging.
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Mandatory Reason Notes Modal for OVERRIDE */}
      {overrideTarget && (
        <Dialog
          title="Security Override · Mandatory Reason"
          description={`Override gate security protocol for plate "${overrideTarget.observation.plate.normalized || "Unknown"}" at ${overrideTarget.observation.gate.name}.`}
          onClose={() => setOverrideTarget(null)}
          size="md"
        >
          <div className="space-y-4">
            <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900 ring-1 ring-amber-200 dark:bg-amber-950/30 dark:text-amber-200 dark:ring-amber-800">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                <div>
                  <p className="font-semibold">Mandatory Security Protocol</p>
                  <p className="mt-0.5">
                    Security regulations mandate an audit explanation when manually
                    overriding plate confidence, unapproved visitor status, or alert
                    restrictions. This log is permanently preserved with your guard ID.
                  </p>
                </div>
              </div>
            </div>

            <div>
              <label
                htmlFor="override-reason"
                className="mb-1 block text-xs font-semibold text-slate-700 dark:text-slate-300"
              >
                Reason Notes <span className="text-rose-500">* (Required)</span>:
              </label>
              <textarea
                id="override-reason"
                rows={3}
                placeholder="e.g., Authorized by Head of Security via radio; physical gate pass verified; VIP convoy accompanying department chair."
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white p-2.5 text-xs focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                autoFocus
              />
              <span className="text-[11px] text-slate-400">
                Minimum 5 characters required to confirm override.
              </span>
            </div>

            <div className="flex justify-end gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
              <Button
                variant="ghost"
                onClick={() => setOverrideTarget(null)}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                className="bg-purple-600 hover:bg-purple-700 dark:bg-purple-600"
                icon={<KeyRound className="h-4 w-4" />}
                disabled={overrideReason.trim().length < 5}
                onClick={handleConfirmOverride}
              >
                Confirm Guard Override
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
