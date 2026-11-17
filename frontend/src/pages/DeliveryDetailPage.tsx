import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Hand, Megaphone, Upload } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useParams } from "react-router";
import { ApiError, api } from "../api/client";
import { DELIVERY_ROOTS, qk, useDelivery, useInvalidate } from "../api/queries";
import type { GuardDecision } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { ChatReply, DecisionBadge, DeliveryLines, InvoiceImage, TotalsCheck, VerdictBadge, flaggedText, sourceLabel } from "../components/delivery/DeliveryParts";
import { UploadInvoiceDialog } from "../components/forms/UploadInvoiceDialog";
import { Button } from "../components/ui/Button";
import { Callout, EmptyState, ErrorNote, ErrorState, Skeleton } from "../components/ui/Feedback";
import { Field, Textarea } from "../components/ui/Form";
import { Detail, DetailList, PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { DECISION_LABEL, formatAmount, formatDateTime, formatPercent } from "../lib/format";

const DECISIONS: { value: GuardDecision; label: string; icon: ReactNode }[] = [
  { value: "CLEARED", label: "Cleared", icon: <CheckCircle2 className="h-4 w-4" /> },
  { value: "HELD", label: "Hold", icon: <Hand className="h-4 w-4" /> },
  { value: "ESCALATED", label: "Escalate", icon: <Megaphone className="h-4 w-4" /> },
];

export function DeliveryDetailPage() {
  const { orderId: raw } = useParams();
  const orderId = raw ? decodeURIComponent(raw) : null;
  const { token } = useSession();
  const notify = useToast();
  const client = useQueryClient();
  const invalidate = useInvalidate();
  const delivery = useDelivery(orderId);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<GuardDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const d = delivery.data;

  const decide = async (decision: GuardDecision) => {
    if (!orderId) return;
    setPending(decision);
    setError(null);
    try {
      const updated = await api.decideDelivery(token, orderId, { decision, note: note.trim() || null });
      client.setQueryData(qk.delivery(orderId), updated);
      setNote("");
      void invalidate(...DELIVERY_ROOTS);
      notify(`Order ${orderId}: ${DECISION_LABEL[decision].toLowerCase()} recorded.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record the decision.");
    } finally {
      setPending(null);
    }
  };

  const header = (
    <PageHeader
      back={{ to: "/deliveries", label: "Deliveries" }}
      title={
        <span className="flex flex-wrap items-center gap-3">
          <span className="font-mono">Order {orderId}</span>
          {d && <VerdictBadge verdict={d.overall} className="text-xs" />}
        </span>
      }
      description={
        d ? (
          <>
            {flaggedText(d)} · {sourceLabel(d.source)}
            {d.gate_id ? ` · ${d.gate_id}` : ""}
            {d.sender ? ` · from ${d.sender}` : ""} · received {formatDateTime(d.received_at)}
          </>
        ) : undefined
      }
    />
  );

  if (delivery.isLoading) {
    return (
      <>
        {header}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <Skeleton className="h-80 lg:col-span-2" />
          <Skeleton className="h-80 lg:col-span-3" />
        </div>
      </>
    );
  }

  if (!d) {
    const notFound = delivery.error instanceof ApiError && delivery.error.status === 404;
    return (
      <>
        {header}
        <div className="card">
          {notFound ? (
            <EmptyState
              title="No invoice for this order ID yet"
              description="Ask the rider to send the invoice at the intake page, or upload it here."
              action={
                <Button variant="primary" icon={<Upload className="h-4 w-4" />} onClick={() => setUploading(true)}>
                  Upload invoice
                </Button>
              }
            />
          ) : (
            <ErrorState error={delivery.error} onRetry={() => void delivery.refetch()} />
          )}
        </div>
        {uploading && (
          <UploadInvoiceDialog
            token={token}
            initialOrderId={orderId ?? ""}
            onClose={() => setUploading(false)}
            onProcessed={(detail) => {
              setUploading(false);
              client.setQueryData(qk.delivery(detail.order_id), detail);
              notify(detail.reply_text || `Order ${detail.order_id} screened.`);
            }}
          />
        )}
      </>
    );
  }

  const inv = d.invoice;
  const history = [...d.decisions].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));

  return (
    <>
      {header}
      <div className="mb-6">
        <Callout title="The guard decides; nothing is blocked automatically.">
          Each line's verdict comes from a fixed policy table (category → reason code → verdict). The overall verdict is the worst line, and at least
          REVIEW when the totals do not add up.
        </Callout>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-2">
          <Section title="Invoice" description={inv.vendor ?? undefined}>
            <InvoiceImage token={token} orderId={d.order_id} className="h-72 w-full sm:h-96" />
            <DetailList className="mt-4 sm:grid-cols-2">
              <Detail label="Subtotal" value={formatAmount(inv.subtotal)} mono />
              <Detail label="Delivery" value={formatAmount(inv.delivery_fee)} mono />
              <Detail label="Total" value={formatAmount(inv.total ?? d.total_amount)} mono />
              <Detail label="Lines add to" value={formatAmount(inv.computed_total)} mono />
              <Detail label="OCR engine" value={inv.ocr_engine} />
              <Detail label="OCR confidence" value={inv.ocr_confidence !== null ? formatPercent(inv.ocr_confidence) : null} />
            </DetailList>
            {inv.raw_ocr_text && (
              <details className="mt-4">
                <summary className="cursor-pointer text-xs font-medium text-slate-600 dark:text-slate-300">Raw OCR text</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800/60 dark:text-slate-300 dark:ring-slate-700">
                  {inv.raw_ocr_text}
                </pre>
              </details>
            )}
          </Section>

          <Section title="Chat reply">
            <ChatReply text={d.reply_text} source={d.source} sender={d.sender} at={d.received_at} />
          </Section>
        </div>

        <div className="space-y-6 lg:col-span-3">
          <Section title="Screened lines" description="Read each line, then screen it: ALLOW, REVIEW or ALERT with a reason code." bodyClassName="p-0">
            <DeliveryLines items={d.items} />
            <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800 sm:px-5">
              <TotalsCheck detail={d} />
            </div>
          </Section>

          <Section title="Guard decision" description="Recorded under your name. Earlier decisions stay in the history.">
            <div className="space-y-3">
              {d.latest_decision ? (
                <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  Current: <DecisionBadge decision={d.latest_decision} />
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {d.latest_decision.by} · {formatDateTime(d.latest_decision.at)}
                  </span>
                </p>
              ) : (
                <p className="text-sm text-slate-700 dark:text-slate-300">{d.overall === "ALLOW" ? "No line was flagged." : "Waiting for a guard decision."}</p>
              )}
              <Field label="Note (optional)">
                <Textarea rows={2} maxLength={1000} placeholder="e.g. Cigarettes returned to rider; rest allowed in" value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <div className="grid grid-cols-3 gap-2">
                {DECISIONS.map((o) => (
                  <Button key={o.value} variant={o.value === "CLEARED" ? "primary" : "secondary"} icon={o.icon} loading={pending === o.value} disabled={pending !== null} onClick={() => void decide(o.value)}>
                    {o.label}
                  </Button>
                ))}
              </div>
              <ErrorNote message={error} />
            </div>
            {history.length > 0 && (
              <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-800">
                <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Decision history</h3>
                <ol className="space-y-2">
                  {history.map((h, i) => (
                    <li key={`${h.at}-${i}`} className="text-sm text-slate-700 dark:text-slate-300">
                      <span className="tabular-nums text-xs text-slate-500 dark:text-slate-400">{formatDateTime(h.at)}</span> ·{" "}
                      <span className="font-medium text-slate-900 dark:text-white">{DECISION_LABEL[h.decision]}</span> by {h.by}
                      {h.note ? <> · “{h.note}”</> : null}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </Section>
        </div>
      </div>
    </>
  );
}
