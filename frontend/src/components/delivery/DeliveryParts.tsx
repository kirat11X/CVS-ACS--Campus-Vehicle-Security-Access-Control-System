import { CheckCircle2, CircleAlert, FileText, ImageOff, Loader2, MessageSquareText, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { useWhatsAppStatus } from "../../api/queries";
import type { DeliveryDecision, DeliveryDetail, DeliveryLine, DeliverySource, DeliverySummary, Verdict } from "../../api/types";
import { cx } from "../../lib/cx";
import { DECISION_LABEL, DELIVERY_SOURCE_LABEL, VERDICT_STYLE, formatAmount, formatDateTime, formatPercent } from "../../lib/format";
import { Dialog } from "../ui/Dialog";
import { Badge } from "../ui/Feedback";

export function VerdictBadge({ verdict, className }: { verdict: Verdict; className?: string }) {
  return (
    <Badge className={cx(VERDICT_STYLE[verdict].badge, "tracking-wide", className)} title="Policy-table outcome; the guard decides">
      {verdict}
    </Badge>
  );
}

export function DecisionBadge({ decision }: { decision: DeliveryDecision }) {
  return (
    <Badge className="bg-slate-900 text-white ring-slate-900 dark:bg-slate-100 dark:text-slate-900 dark:ring-slate-100" title={`${decision.by} · ${formatDateTime(decision.at)}`}>
      {DECISION_LABEL[decision.decision]} by guard
    </Badge>
  );
}

export function sourceLabel(source: DeliverySource): string {
  return DELIVERY_SOURCE_LABEL[source] ?? source;
}

/** "2 of 5 lines need a look" */
export function flaggedText(d: DeliverySummary): string {
  const flagged = d.review_count + d.alert_count;
  if (d.line_count === 0) return "No lines read";
  return flagged === 0 ? `All ${d.line_count} lines allowed` : `${flagged} of ${d.line_count} line${d.line_count === 1 ? "" : "s"} need a look`;
}

/** Invoice photo through the authenticated backend route (PDFs come back as page 1 when the server can render it). */
export function InvoiceImage({ token, orderId, className }: { token: string; orderId: string; className?: string }) {
  const [state, setState] = useState<{ url: string; pdf: boolean } | "loading" | "none">("loading");
  const [enlarged, setEnlarged] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setState("loading");
    api
      .invoiceImage(token, orderId, controller.signal)
      .then(({ blob }) => {
        if (!blob) return setState("none");
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, pdf: blob.type === "application/pdf" });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState("none");
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, orderId]);

  const frame = cx(
    "flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100 ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700",
    className ?? "h-48 w-full",
  );

  if (typeof state === "object" && !state.pdf) {
    return (
      <>
        <button
          type="button"
          className={cx(frame, "group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500")}
          onClick={() => setEnlarged(true)}
          aria-label={`Enlarge invoice for order ${orderId}`}
        >
          <img src={state.url} alt="" className="h-full w-full object-contain transition-transform group-hover:scale-[1.02]" />
        </button>
        {enlarged && (
          <Dialog title={`Invoice · order ${orderId}`} onClose={() => setEnlarged(false)} size="xl">
            <img src={state.url} alt={`Invoice for order ${orderId}`} className="w-full rounded-lg" />
          </Dialog>
        )}
      </>
    );
  }
  return (
    <div className={frame}>
      <span className="flex flex-col items-center gap-1 px-2 text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
        {state === "loading" ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : typeof state === "object" ? (
          <FileText className="h-4 w-4" aria-hidden />
        ) : (
          <ImageOff className="h-4 w-4" aria-hidden />
        )}
        {state === "loading" ? (
          "Loading…"
        ) : typeof state === "object" ? (
          <a href={state.url} target="_blank" rel="noreferrer" className="link">
            Open PDF invoice
          </a>
        ) : (
          "No invoice image"
        )}
      </span>
    </div>
  );
}

/** Each invoice line with category · reason code and its policy verdict. */
export function DeliveryLines({ items, compact = false }: { items: DeliveryLine[]; compact?: boolean }) {
  if (items.length === 0) return <p className="px-4 py-6 text-center text-sm text-slate-500 dark:text-slate-400">No lines were read from this invoice.</p>;
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {items.map((l) => (
        <li key={l.line_no} className={cx("flex items-center gap-3 border-l-4", VERDICT_STYLE[l.verdict].edge, compact ? "px-3 py-2" : "px-4 py-2.5")}>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{l.item_name}</p>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">
              {l.category_label} · <span className="font-mono">{l.reason_code}</span>
              {!compact && l.confidence !== null && <> · read {formatPercent(l.confidence)}</>}
            </p>
          </div>
          {!compact && (
            <div className="hidden text-right text-xs tabular-nums text-slate-600 dark:text-slate-300 sm:block">
              <div>qty {l.quantity ?? "—"}</div>
              <div className="font-medium text-slate-900 dark:text-white">{formatAmount(l.amount)}</div>
            </div>
          )}
          <VerdictBadge verdict={l.verdict} />
        </li>
      ))}
    </ul>
  );
}

/** "Lines add up: 675.00 + 25.00 = 700.00." or why they do not. */
export function TotalsCheck({ detail }: { detail: DeliveryDetail }) {
  const inv = detail.invoice;
  const total = inv.total ?? detail.total_amount;
  const base = inv.subtotal ?? inv.computed_total;
  const parts = [base, inv.delivery_fee].filter((n): n is number => n !== null && n !== undefined);
  const sum = parts.map(formatAmount).join(" + ");

  if (detail.totals_match === true) {
    return (
      <p className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />
        <span>
          Lines add up: <span className="font-mono tabular-nums">{sum ? `${sum} = ${formatAmount(total)}` : formatAmount(total)}</span>.
        </span>
      </p>
    );
  }
  if (detail.totals_match === false) {
    return (
      <p className="flex items-start gap-2 text-sm text-slate-800 dark:text-slate-200">
        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
        <span>
          Lines do not add up: <span className="font-mono tabular-nums">{sum || "—"}</span> gives{" "}
          <span className="font-mono tabular-nums">{formatAmount(inv.computed_total)}</span>, invoice total{" "}
          <span className="font-mono tabular-nums">{formatAmount(total)}</span>. The delivery is at least REVIEW.
        </span>
      </p>
    );
  }
  return <p className="text-sm text-slate-500 dark:text-slate-400">Totals could not be checked: the invoice total was not read.</p>;
}

/** The reply the rider saw on chat / the intake page. */
export function ChatReply({ text, source, sender, at }: { text: string; source: DeliverySource; sender: string | null; at: string }) {
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        <MessageSquareText className="h-3.5 w-3.5" aria-hidden />
        Reply sent · {sourceLabel(source)}
        {sender ? ` · ${sender}` : ""}
      </p>
      <div className="max-w-md rounded-2xl rounded-tl-sm bg-emerald-50 px-3.5 py-2.5 text-sm text-slate-900 ring-1 ring-emerald-200 dark:bg-emerald-500/10 dark:text-slate-100 dark:ring-emerald-500/30">
        {text || "—"}
        <span className="mt-1 block text-right text-[10px] text-slate-500 dark:text-slate-400">{formatDateTime(at)}</span>
      </div>
    </div>
  );
}

/** "Riders can send invoices at http://<ip>:8000/intake" from GET /system/whatsapp. */
export function IntakeHint({ className }: { className?: string }) {
  const status = useWhatsAppStatus();
  const s = status.data;
  if (!s) return null;
  return (
    <div className={cx("flex items-start gap-3 rounded-xl bg-white px-4 py-3 text-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800", className)}>
      <Smartphone className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden />
      <p className="min-w-0 text-slate-700 dark:text-slate-300">
        Riders can send invoices at{" "}
        <a href={s.intake_url} target="_blank" rel="noreferrer" className="link break-all font-mono">
          {s.intake_url}
        </a>{" "}
        from a phone on the campus network.{" "}
        <span className="text-slate-500 dark:text-slate-400">
          {s.provider === "meta" && s.available ? "WhatsApp Business is connected too." : "WhatsApp Business is not connected yet; the local intake page stands in for it."}
        </span>
      </p>
    </div>
  );
}
