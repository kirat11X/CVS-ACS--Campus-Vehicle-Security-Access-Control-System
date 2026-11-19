import { ArrowRight, Package, Upload } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useDeliveries } from "../api/queries";
import type { DeliverySummary, Verdict } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { DecisionBadge, IntakeHint, VerdictBadge, flaggedText, sourceLabel } from "../components/delivery/DeliveryParts";
import { UploadInvoiceDialog } from "../components/forms/UploadInvoiceDialog";
import { Button } from "../components/ui/Button";
import { Callout, EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { SearchInput } from "../components/ui/Form";
import { FilterChips, PageHeader } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { VERDICT_STYLE, formatAmount, formatRelative } from "../lib/format";
import { useDebounced, useNow } from "../lib/hooks";

type VerdictFilter = Verdict | "ALL";
type DecisionFilter = "ALL" | "OPEN" | "DECIDED";

const VERDICTS: VerdictFilter[] = ["ALL", "ALERT", "REVIEW", "ALLOW"];

function DeliveryRow({ d, now }: { d: DeliverySummary; now: number }) {
  return (
    <li>
      <Link
        to={`/deliveries/${encodeURIComponent(d.order_id)}`}
        className={cx(
          "flex flex-wrap items-center gap-x-4 gap-y-1.5 border-l-4 px-4 py-3 hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none dark:hover:bg-slate-800/50 dark:focus-visible:bg-slate-800/50 sm:px-5",
          VERDICT_STYLE[d.overall].edge,
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">{d.order_id}</span>
            <VerdictBadge verdict={d.overall} />
            {d.totals_match === false && d.overall !== "ALLOW" && (
              <span className="text-[11px] font-medium text-amber-700 dark:text-amber-300">totals do not add up</span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
            {flaggedText(d)} · {sourceLabel(d.source)}
            {d.gate_id ? ` · ${d.gate_id}` : ""}
            {d.platform ? ` · ${d.platform}` : ""}
            {d.sender ? ` · ${d.sender}` : ""}
          </p>
        </div>
        <div className="text-right text-xs">
          <div className="font-mono tabular-nums text-slate-900 dark:text-white">{formatAmount(d.total_amount)}</div>
          <div className="text-slate-500 dark:text-slate-400" title={d.received_at}>
            {formatRelative(d.received_at, now)}
          </div>
        </div>
        <div className="w-full sm:w-36 sm:text-right">
          {d.latest_decision ? (
            <DecisionBadge decision={d.latest_decision} />
          ) : (
            <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{d.overall === "ALLOW" ? "No flags" : "Awaiting guard"}</span>
          )}
        </div>
        <ArrowRight className="hidden h-4 w-4 text-slate-400 sm:block" aria-hidden />
      </Link>
    </li>
  );
}

export function DeliveriesPage() {
  const { token } = useSession();
  const notify = useToast();
  const navigate = useNavigate();
  const now = useNow(30_000);
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [uploading, setUploading] = useState(false);

  const verdictParam = params.get("verdict") as VerdictFilter | null;
  const verdict: VerdictFilter = verdictParam && VERDICTS.includes(verdictParam) ? verdictParam : "ALL";
  const decision = (params.get("decision") as DecisionFilter | null) ?? "ALL";
  const setParam = (key: string, value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value === "ALL" || value === "") next.delete(key);
        else next.set(key, value);
        return next;
      },
      { replace: true },
    );

  const q = search.trim();
  const debouncedQ = useDebounced(q, 300);
  const list = useDeliveries({ q: debouncedQ || undefined, limit: 100 });
  const all = useMemo(() => list.data ?? [], [list.data]);
  const byDecision = all.filter((d) => decision === "ALL" || (decision === "DECIDED" ? !!d.latest_decision : !d.latest_decision && d.overall !== "ALLOW"));
  const visible = byDecision.filter((d) => verdict === "ALL" || d.overall === verdict);
  const counts = useMemo(() => {
    const out: Record<VerdictFilter, number> = { ALL: byDecision.length, ALERT: 0, REVIEW: 0, ALLOW: 0 };
    for (const d of byDecision) out[d.overall]++;
    return out;
  }, [byDecision]);

  // The rider's order ID opens the item list.
  const open = (e: FormEvent) => {
    e.preventDefault();
    if (!q) return;
    const exact = all.find((d) => d.order_id.toLowerCase() === q.toLowerCase());
    navigate(`/deliveries/${encodeURIComponent(exact?.order_id ?? q)}`);
  };

  return (
    <>
      <PageHeader
        title="Deliveries"
        description="Invoices sent by riders or uploaded here. Each line is read and screened by a fixed policy table: ALLOW, REVIEW or ALERT."
        actions={
          <Button variant="primary" icon={<Upload className="h-4 w-4" />} onClick={() => setUploading(true)}>
            Upload invoice
          </Button>
        }
      />

      <div className="mb-4 space-y-3">
        <Callout title="The guard decides; nothing is blocked automatically.">
          Verdicts come from the policy table, never from OCR or ML. Flagged lines wait for your Cleared, Hold or Escalate.
        </Callout>
        <IntakeHint />
      </div>

      <div className="mb-4 space-y-3">
        <form onSubmit={open} className="flex max-w-lg gap-2" role="search">
          <SearchInput
            label="Order ID"
            placeholder="Rider's order ID, e.g. D-20481"
            value={search}
            onChange={(v) => {
              setSearch(v);
              setParam("q", v.trim());
            }}
            className="flex-1"
            mono
          />
          <Button type="submit" disabled={!q}>
            Open
          </Button>
        </form>
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <FilterChips<VerdictFilter>
            label="Verdict"
            value={verdict}
            onChange={(v) => setParam("verdict", v)}
            options={VERDICTS.map((v) => ({ value: v, label: v === "ALL" ? "All" : v.charAt(0) + v.slice(1).toLowerCase(), count: counts[v] }))}
          />
          <FilterChips<DecisionFilter>
            label="Guard decision"
            value={decision}
            onChange={(v) => setParam("decision", v)}
            options={[
              { value: "ALL", label: "Any decision" },
              { value: "OPEN", label: "Awaiting guard" },
              { value: "DECIDED", label: "Decided" },
            ]}
          />
        </div>
      </div>

      <div className="card overflow-hidden">
        {list.isLoading ? (
          <SkeletonRows rows={5} />
        ) : list.isError && !list.data ? (
          <ErrorState error={list.error} onRetry={() => void list.refetch()} />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<Package className="h-5 w-5" />}
            title={all.length === 0 ? (q ? "No delivery with this order ID" : "No deliveries yet") : "Nothing matches these filters"}
            description={all.length === 0 ? "Invoices sent through the intake page, WhatsApp or the Upload button appear here." : "Clear a filter to see more."}
          />
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {visible.map((d) => (
              <DeliveryRow key={d.order_id} d={d} now={now} />
            ))}
          </ul>
        )}
      </div>

      {uploading && (
        <UploadInvoiceDialog
          token={token}
          initialOrderId={q}
          onClose={() => setUploading(false)}
          onProcessed={(detail) => {
            setUploading(false);
            notify(detail.reply_text || `Order ${detail.order_id} screened.`);
            navigate(`/deliveries/${encodeURIComponent(detail.order_id)}`);
          }}
        />
      )}
    </>
  );
}
