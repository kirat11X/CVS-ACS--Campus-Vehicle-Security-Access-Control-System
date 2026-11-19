import { useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Ban,
  CheckCircle2,
  Hand,
  Package,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  Truck,
  Upload,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { ApiError, api } from "../api/client";
import {
  DELIVERY_ROOTS,
  qk,
  useDeliveries,
  useDelivery,
  useInvalidate,
} from "../api/queries";
import type {
  DeliveryDecision,
  DeliveryDetail,
  DeliveryLine,
  DeliverySummary,
  GuardDecision,
  Verdict,
} from "../api/types";
import { useSession } from "../auth/AuthContext";
import {
  ChatReply,
  DecisionBadge,
  InvoiceImage,
  TotalsCheck,
  VerdictBadge,
  flaggedText,
  sourceLabel,
} from "../components/delivery/DeliveryParts";
import { UploadInvoiceDialog } from "../components/forms/UploadInvoiceDialog";
import { ReasonCodeBadge } from "../components/ReasonCodeBadge";
import { Button } from "../components/ui/Button";
import {
  Badge,
  EmptyState,
  ErrorState,
  Skeleton,
  SkeletonRows,
} from "../components/ui/Feedback";
import { Input, SearchInput } from "../components/ui/Form";
import { FilterChips, PageHeader } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import {
  DECISION_LABEL,
  VERDICT_STYLE,
  formatAmount,
  formatDateTime,
  formatRelative,
} from "../lib/format";
import { useDebounced, useNow } from "../lib/hooks";

type VerdictFilter = Verdict | "ALL" | "ACTION_REQUIRED";

/** Map platform to color theme & badge */
function getPlatformBadge(platform: string | null) {
  const p = (platform || "").toUpperCase();
  if (p.includes("ZOMATO")) {
    return {
      name: "Zomato",
      cls: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-500/30",
    };
  }
  if (p.includes("SWIGGY")) {
    return {
      name: "Swiggy",
      cls: "bg-orange-50 text-orange-700 ring-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:ring-orange-500/30",
    };
  }
  if (p.includes("AMAZON")) {
    return {
      name: "Amazon",
      cls: "bg-amber-50 text-amber-800 ring-amber-300 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30",
    };
  }
  if (p.includes("FLIPKART")) {
    return {
      name: "Flipkart",
      cls: "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-500/30",
    };
  }
  if (p.includes("BLINKIT") || p.includes("ZEPTO") || p.includes("INSTAMART")) {
    return {
      name: platform || "Quick Commerce",
      cls: "bg-yellow-50 text-yellow-800 ring-yellow-300 dark:bg-yellow-500/10 dark:text-yellow-200 dark:ring-yellow-500/30",
    };
  }
  if (p.includes("UBER")) {
    return {
      name: "Uber",
      cls: "bg-slate-900 text-slate-100 ring-slate-700 dark:bg-slate-800 dark:text-white dark:ring-slate-600",
    };
  }
  if (p.includes("RELIANCE")) {
    return {
      name: "Reliance",
      cls: "bg-emerald-50 text-emerald-800 ring-emerald-300 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30",
    };
  }
  return {
    name: platform || "Courier",
    cls: "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
  };
}

/** Per-line policy badge component */
function LinePolicyBadge({ verdict }: { verdict: Verdict }) {
  if (verdict === "ALLOW") {
    return (
      <Badge
        className="bg-emerald-50 text-emerald-800 ring-emerald-600/30 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30"
        title="Item policy approved: Allowed on campus"
      >
        <ShieldCheck className="h-3 w-3" />
        <span>ALLOW</span>
      </Badge>
    );
  }
  if (verdict === "REVIEW") {
    return (
      <Badge
        className="bg-amber-50 text-amber-800 ring-amber-600/30 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/40"
        title="Item policy ambiguous or requires approval (e.g., hazmat, prescription medicine)"
      >
        <AlertTriangle className="h-3 w-3" />
        <span>REVIEW</span>
      </Badge>
    );
  }
  return (
    <Badge
      className="bg-rose-50 text-rose-800 ring-rose-600/30 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30"
      title="Prohibited item detected (e.g., tobacco, alcohol, weapons)"
    >
      <Ban className="h-3 w-3" />
      <span>ALERT</span>
    </Badge>
  );
}

interface VerificationDetailProps {
  orderId: string;
  token: string;
  onDecisionRecorded: (orderId: string, decision: GuardDecision) => void;
}

function DeliveryVerificationDetail({
  orderId,
  token,
  onDecisionRecorded,
}: VerificationDetailProps) {
  const delivery = useDelivery(orderId);
  const notify = useToast();
  const invalidate = useInvalidate();
  const client = useQueryClient();

  const [notes, setNotes] = useState("");
  const [pendingAction, setPendingAction] = useState<GuardDecision | null>(null);
  const [error, setError] = useState<string | null>(null);

  const d = delivery.data;

  const handleDecision = async (
    decision: GuardDecision,
    defaultNote: string,
  ) => {
    setPendingAction(decision);
    setError(null);
    const finalNote = (notes.trim() || defaultNote).trim();

    try {
      const updated = await api.decideDelivery(token, orderId, {
        decision,
        note: finalNote,
      });
      client.setQueryData(qk.delivery(orderId), updated);
      void invalidate(...DELIVERY_ROOTS);
      onDecisionRecorded(orderId, decision);

      const labelMap = {
        CLEARED: "Approved & Gate Opened",
        HELD: "Flagged for Physical Search",
        ESCALATED: "Delivery Denied",
      };
      notify(`Order ${orderId}: ${labelMap[decision]}`);
      setNotes("");
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Failed to record guard action.",
      );
    } finally {
      setPendingAction(null);
    }
  };

  if (delivery.isLoading) {
    return (
      <div className="card space-y-4 p-6">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  if (delivery.isError || !d) {
    return (
      <div className="card p-6">
        <ErrorState
          error={delivery.error}
          onRetry={() => void delivery.refetch()}
        />
      </div>
    );
  }

  const platformInfo = getPlatformBadge(d.platform);
  const reasonCode =
    d.overall === "ALERT"
      ? "ALERT_RESTRICTED_ITEM"
      : d.overall === "REVIEW"
        ? "REVIEW_UNKNOWN_VEHICLE"
        : "ALLOW_REGISTERED_VEHICLE";

  return (
    <div className="card space-y-6 overflow-hidden p-5 sm:p-6">
      {/* Header Info */}
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5 dark:border-slate-800">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-xl font-bold tracking-tight text-slate-900 dark:text-white">
              Order {d.order_id}
            </h2>
            <Badge className={cx("text-xs font-medium", platformInfo.cls)}>
              <Truck className="h-3 w-3" />
              {platformInfo.name}
            </Badge>
            <VerdictBadge verdict={d.overall} />
            <ReasonCodeBadge code={reasonCode} compact />
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {sourceLabel(d.source)} · Gate {d.gate_id || "Main Entrance"} ·
            Sender: {d.sender || "Delivery Partner"} · Received{" "}
            {formatDateTime(d.received_at)}
          </p>
        </div>

        <div className="text-right">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            Invoice Total
          </div>
          <div className="font-mono text-lg font-bold text-slate-900 dark:text-white">
            {formatAmount(d.total_amount)}
          </div>
          {d.overall === "ALLOW" ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-3 w-3" /> System Cleared
            </span>
          ) : d.overall === "ALERT" ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400">
              <AlertCircle className="h-3 w-3" /> Contraband Flagged
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-600 dark:text-amber-400">
              <AlertTriangle className="h-3 w-3" /> Flagged for Search
            </span>
          )}
        </div>
      </div>

      {/* Invoice Image & OCR Check */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Invoice Capture
          </h3>
          <InvoiceImage
            token={token}
            orderId={d.order_id}
            className="h-44 w-full"
          />
        </div>
        <div className="flex flex-col justify-between rounded-lg bg-slate-50 p-4 ring-1 ring-slate-200 dark:bg-slate-800/40 dark:ring-slate-700 lg:col-span-2">
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Automated Intake & Policy Screening
            </h3>
            <TotalsCheck detail={d} />
            <p className="text-xs text-slate-600 dark:text-slate-400">
              {d.line_count} line items extracted via OCR. Per-line policy
              checks determine prohibited cargo. Final entry decision is
              mandated to the on-duty guard.
            </p>
          </div>
          {d.reply_text && (
            <div className="mt-3">
              <ChatReply
                text={d.reply_text}
                source={d.source}
                sender={d.sender}
                at={d.received_at}
              />
            </div>
          )}
        </div>
      </div>

      {/* Extracted Line Items with per-line policy badges */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Extracted Line Items ({d.items?.length ?? 0})
          </h3>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {flaggedText(d)}
          </span>
        </div>

        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm dark:divide-slate-800">
            <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2.5">#</th>
                <th className="px-3 py-2.5">Item Name & Category</th>
                <th className="px-3 py-2.5 text-center">Qty</th>
                <th className="px-3 py-2.5 text-right">Amount</th>
                <th className="px-3 py-2.5 text-center">Policy Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {!d.items || d.items.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-6 text-center text-xs text-slate-500"
                  >
                    No line items extracted from invoice.
                  </td>
                </tr>
              ) : (
                d.items.map((item: DeliveryLine) => (
                  <tr
                    key={item.line_no}
                    className={cx(
                      "hover:bg-slate-50/50 dark:hover:bg-slate-800/30",
                      item.verdict === "ALERT" &&
                        "bg-rose-50/40 dark:bg-rose-950/20",
                      item.verdict === "REVIEW" &&
                        "bg-amber-50/30 dark:bg-amber-950/20",
                    )}
                  >
                    <td className="px-3 py-2.5 font-mono text-xs text-slate-400">
                      {item.line_no}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="font-medium text-slate-900 dark:text-white">
                        {item.item_name}
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">
                        {item.category_label} ·{" "}
                        <span className="font-mono">{item.reason_code}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-center font-mono text-xs tabular-nums text-slate-700 dark:text-slate-300">
                      {item.quantity ?? "1"}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums text-slate-700 dark:text-slate-300">
                      {formatAmount(item.amount)}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <LinePolicyBadge verdict={item.verdict} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Guard Decision Section */}
      <div className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-900/40">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
            Guard Actions & Gate Control
          </h3>
          {d.latest_decision && <DecisionBadge decision={d.latest_decision} />}
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-700 ring-1 ring-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:ring-rose-800">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div>
          <label
            htmlFor="guard-notes"
            className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400"
          >
            Optional Guard Notes / Physical Verification Observation:
          </label>
          <Input
            id="guard-notes"
            placeholder="e.g. Verified package seal, rider phone matched, no prohibited alcohol/tobacco found."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="text-xs"
          />
        </div>

        {/* 3 Prominent Guard Action Buttons */}
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
          <Button
            type="button"
            variant="primary"
            className="w-full bg-emerald-600 hover:bg-emerald-700 dark:bg-emerald-600 dark:hover:bg-emerald-500"
            icon={<CheckCircle2 className="h-4 w-4" />}
            loading={pendingAction === "CLEARED"}
            disabled={pendingAction !== null}
            onClick={() =>
              handleDecision(
                "CLEARED",
                "Approve Delivery & Open Gate - All clear",
              )
            }
          >
            Approve Delivery & Open Gate
          </Button>

          <Button
            type="button"
            className="w-full border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 dark:border-amber-700/60 dark:bg-amber-500/20 dark:text-amber-200 dark:hover:bg-amber-500/30"
            icon={<Hand className="h-4 w-4 text-amber-600 dark:text-amber-400" />}
            loading={pendingAction === "HELD"}
            disabled={pendingAction !== null}
            onClick={() =>
              handleDecision("HELD", "Flag for Physical Search at Gate")
            }
          >
            Flag for Physical Search
          </Button>

          <Button
            type="button"
            className="w-full border-rose-300 bg-rose-50 text-rose-900 hover:bg-rose-100 dark:border-rose-700/60 dark:bg-rose-500/20 dark:text-rose-200 dark:hover:bg-rose-500/30"
            icon={<Ban className="h-4 w-4 text-rose-600 dark:text-rose-400" />}
            loading={pendingAction === "ESCALATED"}
            disabled={pendingAction !== null}
            onClick={() =>
              handleDecision("ESCALATED", "Deny Delivery - Access Denied")
            }
          >
            Deny Delivery
          </Button>
        </div>

        {/* Audit Log / History for this delivery */}
        {d.decisions && d.decisions.length > 0 && (
          <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-800">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Audit Trail
            </p>
            <ul className="mt-1.5 space-y-1">
              {d.decisions.map((dec: DeliveryDecision, idx: number) => (
                <li
                  key={idx}
                  className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400"
                >
                  <span>
                    <strong className="text-slate-900 dark:text-white">
                      {DECISION_LABEL[dec.decision]}
                    </strong>{" "}
                    by {dec.by}: {dec.note || "No notes"}
                  </span>
                  <span className="font-mono text-[10px] tabular-nums text-slate-400">
                    {formatDateTime(dec.at)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export function DeliveryVerificationPage() {
  const { token } = useSession();
  const now = useNow(30_000);
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [uploading, setUploading] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);

  const selectedFromParam = params.get("orderId");
  const activeOrderId = selectedOrderId || selectedFromParam;

  const verdictParam = params.get("verdict") as VerdictFilter | null;
  const verdict: VerdictFilter = verdictParam ?? "ALL";

  const debouncedQ = useDebounced(search.trim(), 300);
  const deliveriesQuery = useDeliveries({
    q: debouncedQ || undefined,
    limit: 100,
  });

  const allDeliveries = useMemo(
    () => deliveriesQuery.data ?? [],
    [deliveriesQuery.data],
  );

  // Filter deliveries based on query and verdict filter
  const filteredDeliveries = useMemo(() => {
    return allDeliveries.filter((d) => {
      if (verdict === "ALL") return true;
      if (verdict === "ACTION_REQUIRED") {
        return (
          (d.overall === "ALERT" || d.overall === "REVIEW") &&
          !d.latest_decision
        );
      }
      return d.overall === verdict;
    });
  }, [allDeliveries, verdict]);

  // Set default selected order if none selected
  const effectiveOrderId =
    activeOrderId && allDeliveries.some((d) => d.order_id === activeOrderId)
      ? activeOrderId
      : (filteredDeliveries[0]?.order_id ?? null);

  const counts = useMemo(() => {
    let alert = 0;
    let review = 0;
    let allow = 0;
    let pending = 0;

    for (const d of allDeliveries) {
      if (d.overall === "ALERT") alert++;
      if (d.overall === "REVIEW") review++;
      if (d.overall === "ALLOW") allow++;
      if (
        (d.overall === "ALERT" || d.overall === "REVIEW") &&
        !d.latest_decision
      ) {
        pending++;
      }
    }
    return { all: allDeliveries.length, alert, review, allow, pending };
  }, [allDeliveries]);

  const setVerdict = (v: VerdictFilter) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (v === "ALL") next.delete("verdict");
        else next.set("verdict", v);
        return next;
      },
      { replace: true },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            <PackageCheck className="h-6 w-6 text-sky-600 dark:text-sky-400" />
            <span>Delivery Verification Queue</span>
          </span>
        }
        description="Verify incoming couriers (Zomato, Swiggy, Amazon, couriers), inspect OCR extracted items against safety policies, and approve gate access."
        actions={
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              icon={<Upload className="h-3.5 w-3.5" />}
              onClick={() => setUploading(true)}
            >
              Upload Invoice
            </Button>
            <Button
              size="sm"
              variant="ghost"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => void deliveriesQuery.refetch()}
            >
              Refresh
            </Button>
          </div>
        }
      />

      {/* KPI Stats Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Total Deliveries
          </div>
          <div className="mt-1 text-2xl font-bold text-slate-900 dark:text-white">
            {counts.all}
          </div>
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3.5 dark:border-amber-800/50 dark:bg-amber-950/20">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-800 dark:text-amber-300">
            Requires Action
          </div>
          <div className="mt-1 text-2xl font-bold text-amber-900 dark:text-amber-200">
            {counts.pending}
          </div>
        </div>

        <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3.5 dark:border-rose-800/50 dark:bg-rose-950/20">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-800 dark:text-rose-300">
            Policy Alerts
          </div>
          <div className="mt-1 text-2xl font-bold text-rose-900 dark:text-rose-200">
            {counts.alert}
          </div>
        </div>

        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5 dark:border-emerald-800/50 dark:bg-emerald-950/20">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800 dark:text-emerald-300">
            Auto-Allowed
          </div>
          <div className="mt-1 text-2xl font-bold text-emerald-900 dark:text-emerald-200">
            {counts.allow}
          </div>
        </div>
      </div>

      {/* Filters and Search */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="w-full sm:max-w-xs">
          <SearchInput
            label="Search orders"
            placeholder="Search order ID, rider, or gate..."
            value={search}
            onChange={setSearch}
          />
        </div>

        <FilterChips<VerdictFilter>
          label="Filter by verdict"
          value={verdict}
          onChange={setVerdict}
          options={[
            {
              value: "ALL",
              label: `All (${counts.all})`,
            },
            {
              value: "ACTION_REQUIRED",
              label: `Requires Action (${counts.pending})`,
            },
            {
              value: "ALERT",
              label: `Alerts (${counts.alert})`,
            },
            {
              value: "REVIEW",
              label: `Review (${counts.review})`,
            },
            {
              value: "ALLOW",
              label: `Allowed (${counts.allow})`,
            },
          ]}
        />
      </div>

      {/* Main Two-Column View: Queue on Left, Verification Action Panel on Right */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Side: Delivery Queue List */}
        <div className="space-y-2 lg:col-span-5">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Incoming Queue ({filteredDeliveries.length})
            </span>
          </div>

          <div className="max-h-[820px] overflow-y-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            {deliveriesQuery.isLoading ? (
              <SkeletonRows rows={6} />
            ) : filteredDeliveries.length === 0 ? (
              <EmptyState
                icon={<Package className="h-6 w-6" />}
                title="No deliveries match criteria"
                description="Incoming delivery rider invoices sent via WhatsApp or intake will appear here automatically."
              />
            ) : (
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {filteredDeliveries.map((d: DeliverySummary) => {
                  const isSelected = d.order_id === effectiveOrderId;
                  const platform = getPlatformBadge(d.platform);
                  const edgeStyle = VERDICT_STYLE[d.overall].edge;

                  return (
                    <li key={d.order_id}>
                      <button
                        type="button"
                        onClick={() => setSelectedOrderId(d.order_id)}
                        className={cx(
                          "w-full border-l-4 px-4 py-3 text-left transition-colors focus-visible:outline-none",
                          edgeStyle,
                          isSelected
                            ? "bg-sky-50/70 ring-1 ring-inset ring-sky-300 dark:bg-slate-800/80 dark:ring-sky-600"
                            : "hover:bg-slate-50 dark:hover:bg-slate-800/40",
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-mono text-xs font-bold text-slate-900 dark:text-white">
                                {d.order_id}
                              </span>
                              <Badge
                                className={cx(
                                  "px-1.5 py-0 text-[10px]",
                                  platform.cls,
                                )}
                              >
                                {platform.name}
                              </Badge>
                              <VerdictBadge
                                verdict={d.overall}
                                className="scale-90 text-[10px]"
                              />
                            </div>
                            <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
                              {flaggedText(d)} · {sourceLabel(d.source)}
                              {d.gate_id ? ` · ${d.gate_id}` : ""}
                            </p>
                          </div>

                          <div className="shrink-0 text-right">
                            <div className="font-mono text-xs font-semibold tabular-nums text-slate-900 dark:text-white">
                              {formatAmount(d.total_amount)}
                            </div>
                            <div className="text-[10px] text-slate-400">
                              {formatRelative(d.received_at, now)}
                            </div>
                          </div>
                        </div>

                        <div className="mt-2 flex items-center justify-between text-[11px]">
                          <div>
                            {d.latest_decision ? (
                              <DecisionBadge decision={d.latest_decision} />
                            ) : (
                              <span
                                className={cx(
                                  "font-medium",
                                  d.overall === "ALLOW"
                                    ? "text-slate-500"
                                    : "font-semibold text-amber-600 dark:text-amber-400",
                                )}
                              >
                                {d.overall === "ALLOW"
                                  ? "No flags"
                                  : "Awaiting guard triage"}
                              </span>
                            )}
                          </div>
                          <span className="text-xs text-sky-600 dark:text-sky-400">
                            {isSelected ? "Inspecting →" : "Select"}
                          </span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Right Side: Active Delivery Inspection & Action Panel */}
        <div className="lg:col-span-7">
          {effectiveOrderId ? (
            <DeliveryVerificationDetail
              orderId={effectiveOrderId}
              token={token}
              onDecisionRecorded={() => void deliveriesQuery.refetch()}
            />
          ) : (
            <div className="card flex h-64 flex-col items-center justify-center p-6 text-center">
              <PackageCheck className="mb-2 h-10 w-10 text-slate-400" />
              <p className="text-sm font-semibold text-slate-900 dark:text-white">
                Select a delivery to verify
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Choose an incoming courier from the queue to view extracted
                items, policy verdicts, and control the gate.
              </p>
            </div>
          )}
        </div>
      </div>

      {uploading && (
        <UploadInvoiceDialog
          token={token}
          onProcessed={(created: DeliveryDetail) => {
            setUploading(false);
            setSelectedOrderId(created.order_id);
            void deliveriesQuery.refetch();
          }}
          onClose={() => setUploading(false)}
        />
      )}
    </div>
  );
}
