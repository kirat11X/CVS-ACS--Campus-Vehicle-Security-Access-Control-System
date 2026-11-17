import { ArrowRight, Package } from "lucide-react";
import { useDeliveries, useDelivery } from "../../api/queries";
import type { DeliverySource } from "../../api/types";
import { ButtonLink } from "../ui/Button";
import { EmptyState, ErrorState, Skeleton } from "../ui/Feedback";
import { Section } from "../ui/Layout";
import { DecisionBadge, DeliveryLines, InvoiceImage, TotalsCheck, VerdictBadge, flaggedText, sourceLabel } from "./DeliveryParts";

const SENT_VIA: Record<DeliverySource, string> = {
  WHATSAPP: "sent on chat",
  LOCAL_INTAKE: "sent at the intake page",
  CONSOLE: "uploaded at the console",
};

/** Live console panel: the latest delivery still waiting for a guard (else the latest one). */
export function DeliveryScreeningPanel({ token }: { token: string }) {
  const list = useDeliveries({ limit: 20 }, 15_000);
  const items = list.data ?? [];
  const latest = items.find((d) => d.overall !== "ALLOW" && !d.latest_decision) ?? items[0] ?? null;
  const detail = useDelivery(latest?.order_id ?? null);
  const d = detail.data;

  return (
    <Section
      title="Delivery screening"
      description={
        latest
          ? `Order ${latest.order_id}${latest.gate_id ? ` · ${latest.gate_id}` : ""} · ${SENT_VIA[latest.source] ?? sourceLabel(latest.source)} · ${flaggedText(latest)}`
          : "The rider's order ID opens the item list; each line gets ALLOW, REVIEW or ALERT."
      }
      actions={
        <ButtonLink to={latest ? `/deliveries/${encodeURIComponent(latest.order_id)}` : "/deliveries"} size="sm" variant="ghost">
          {latest ? "Open order" : "Deliveries"} <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </ButtonLink>
      }
      bodyClassName="p-0"
    >
      {list.isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : list.isError && !list.data ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !latest ? (
        <EmptyState icon={<Package className="h-5 w-5" />} title="No deliveries yet" description="Invoices sent by riders at the intake page appear here." />
      ) : (
        <div className="flex flex-col gap-4 p-4 sm:flex-row sm:p-5">
          <InvoiceImage token={token} orderId={latest.order_id} className="h-40 w-full sm:h-44 sm:w-36" />
          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">{latest.order_id}</span>
              <VerdictBadge verdict={latest.overall} />
              {latest.latest_decision ? (
                <DecisionBadge decision={latest.latest_decision} />
              ) : (
                <span className="text-xs text-slate-500 dark:text-slate-400">Awaiting guard · nothing is blocked automatically</span>
              )}
            </div>
            <div className="overflow-hidden rounded-lg ring-1 ring-slate-200 dark:ring-slate-700">
              {d ? <DeliveryLines items={d.items} compact /> : detail.isError ? <ErrorState error={detail.error} /> : <Skeleton className="h-24 rounded-none" />}
            </div>
            {d && <TotalsCheck detail={d} />}
          </div>
        </div>
      )}
    </Section>
  );
}
