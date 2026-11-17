import { CheckCircle2, CircleAlert, Database, Globe, MessageSquareText, Radio, RefreshCw, Server, Video } from "lucide-react";
import type { ReactNode } from "react";
import { useHealth, useWhatsAppStatus } from "../api/queries";
import { CONNECTION_DISPLAY } from "../components/feed/ConnectionIndicator";
import { Button } from "../components/ui/Button";
import { Callout, ErrorState, errorMessage } from "../components/ui/Feedback";
import { Detail, DetailList, PageHeader } from "../components/ui/Layout";
import { useFeed } from "../feed/LiveFeedContext";
import { cx } from "../lib/cx";
import { formatTime, humanize } from "../lib/format";
import { describeServer, isNativeApp, platformName } from "../lib/platform";

const PROVIDER_LABEL: Record<string, string> = {
  local: "Local intake (LAN)",
  mock: "Mock provider",
  meta: "WhatsApp Business API",
};

function Status({ ok, label }: { ok: boolean | null; label?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-sm font-medium", ok === null ? "text-slate-500" : "text-slate-900 dark:text-white")}>
      {ok === null ? (
        <span className="h-2 w-2 animate-pulse rounded-full bg-slate-300" aria-hidden />
      ) : ok ? (
        <CheckCircle2 className="h-4 w-4 text-sky-600 dark:text-sky-400" aria-hidden />
      ) : (
        <CircleAlert className="h-4 w-4 text-amber-600 dark:text-amber-400" aria-hidden />
      )}
      {label ?? (ok === null ? "Checking" : ok ? "Connected" : "Problem")}
    </span>
  );
}

function Component({ icon, title, status, children }: { icon: ReactNode; title: string; status: ReactNode; children: ReactNode }) {
  return (
    <div className="card p-4 sm:p-5">
      <div className="mb-3 flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{icon}</span>
        <h2 className="flex-1 text-sm font-semibold text-slate-900 dark:text-white">{title}</h2>
        {status}
      </div>
      {children}
    </div>
  );
}

export function SystemPage() {
  const health = useHealth(10_000);
  const whatsapp = useWhatsAppStatus();
  const wa = whatsapp.data;
  const feed = useFeed();
  const h = health.data;
  const pending = health.isLoading;
  const stats = h?.frigate_worker.stats ?? {};

  return (
    <>
      <PageHeader
        title="System status"
        description="Live checks of every link in the chain: this app → API server → PostgreSQL, MQTT broker → Frigate ingestion → live stream. Refreshes every 10 seconds."
        actions={
          <Button size="sm" icon={<RefreshCw className={cx("h-3.5 w-3.5", health.isFetching && "animate-spin")} />} onClick={() => void health.refetch()}>
            Check now
          </Button>
        }
      />

      {health.isError && (
        <div className="mb-6">
          <Callout tone="notice" title="The API server is not answering">
            {errorMessage(health.error)} Requests go to {describeServer()}.
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Component icon={<Globe className="h-4 w-4" />} title="API server" status={<Status ok={pending ? null : !health.isError} label={pending ? undefined : health.isError ? "Unreachable" : "Reachable"} />}>
          <DetailList className="sm:grid-cols-2">
            <Detail label="Address" value={describeServer()} mono />
            <Detail label="Overall" value={h ? humanize(h.status) : health.isError ? "Unreachable" : "…"} />
            <Detail label="Last check" value={health.dataUpdatedAt ? formatTime(new Date(health.dataUpdatedAt).toISOString()) : "—"} />
            <Detail label="Client" value={`${isNativeApp ? `${humanize(platformName)} app` : "Web"} · v${__APP_VERSION__}`} />
          </DetailList>
        </Component>

        <Component icon={<Database className="h-4 w-4" />} title="PostgreSQL" status={<Status ok={h ? h.database.status === "ok" : pending ? null : false} />}>
          {h ? (
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {h.database.status === "ok" ? "Authoritative campus state is reachable (SELECT 1 succeeded)." : String(h.database.detail ?? "Database error")}
            </p>
          ) : (
            <p className="text-sm text-slate-500">{pending ? "Checking…" : "Unknown while the API server is unreachable."}</p>
          )}
        </Component>

        <Component icon={<Server className="h-4 w-4" />} title="MQTT broker" status={<Status ok={h ? h.mqtt.status === "ok" : pending ? null : false} />}>
          {h ? (
            h.mqtt.status === "ok" ? (
              <DetailList className="sm:grid-cols-2">
                <Detail label="Broker" value={String(h.mqtt.broker ?? "—")} mono />
                <Detail label="Round trip" value={`${String(h.mqtt.latency_ms ?? "?")} ms`} />
              </DetailList>
            ) : (
              <p className="text-sm text-slate-600 dark:text-slate-400">{String(h.mqtt.detail ?? "Broker error")}</p>
            )
          ) : (
            <p className="text-sm text-slate-500">{pending ? "Checking…" : "Unknown"}</p>
          )}
        </Component>

        <Component
          icon={<Video className="h-4 w-4" />}
          title="Frigate ingestion worker"
          status={<Status ok={h ? h.frigate_worker.running && h.frigate_worker.connected : pending ? null : false} label={h ? (h.frigate_worker.connected ? "Subscribed" : h.frigate_worker.running ? "Not connected" : "Stopped") : undefined} />}
        >
          {h ? (
            <DetailList className="sm:grid-cols-3">
              <Detail label="Topic" value={h.frigate_worker.topic} mono />
              <Detail label="Messages" value={stats.messages_received ?? 0} />
              <Detail label="New sightings" value={stats.observations_created ?? 0} />
              <Detail label="Refinements" value={stats.observations_updated ?? 0} />
              <Detail label="Unmapped cameras" value={stats.unmapped_cameras ?? 0} />
              <Detail label="Errors" value={(stats.errors ?? 0) + (stats.malformed_payloads ?? 0)} />
            </DetailList>
          ) : (
            <p className="text-sm text-slate-500">{pending ? "Checking…" : "Unknown"}</p>
          )}
          <p className="hint mt-3">Counts since the API server started. Frigate itself is checked indirectly: no messages means no camera events are reaching the broker.</p>
        </Component>

        <Component
          icon={<Radio className="h-4 w-4" />}
          title="Live stream (this device)"
          status={<Status ok={feed.connection === "live" ? true : feed.connection === "connecting" ? null : false} label={CONNECTION_DISPLAY[feed.connection].label} />}
        >
          <DetailList className="sm:grid-cols-2">
            <Detail label="State" value={CONNECTION_DISPLAY[feed.connection].detail} />
            <Detail label="Last sync" value={feed.lastSyncAt ? formatTime(new Date(feed.lastSyncAt).toISOString()) : "—"} />
            <Detail label="Sightings held" value={feed.cards.length} />
            <Detail label="Reads to review" value={feed.needsReview} />
          </DetailList>
        </Component>

        <Component
          icon={<MessageSquareText className="h-4 w-4" />}
          title="Invoice messaging (WhatsApp)"
          status={<Status ok={wa ? wa.available : whatsapp.isLoading ? null : false} label={wa ? PROVIDER_LABEL[wa.provider] ?? humanize(wa.provider) : whatsapp.isError ? "Unknown" : undefined} />}
        >
          {wa ? (
            <>
              <DetailList className="sm:grid-cols-3">
                <Detail label="Provider" value={PROVIDER_LABEL[wa.provider] ?? wa.provider} />
                <Detail label="Available" value={wa.available ? "Yes" : "No"} />
                <Detail label="Replies held (outbox)" value={wa.outbox_count} />
              </DetailList>
              <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2.5 text-sm ring-1 ring-slate-200 dark:bg-slate-800/60 dark:ring-slate-700">
                <span className="text-slate-600 dark:text-slate-400">Local intake page: </span>
                <a href={wa.intake_url} target="_blank" rel="noreferrer" className="link break-all font-mono">
                  {wa.intake_url}
                </a>
              </div>
              <p className="hint mt-3">
                {wa.provider === "meta"
                  ? "Invoices also arrive from the WhatsApp Business API webhook."
                  : "WhatsApp Business API is not connected yet. Riders open the intake page on a phone on the campus network, enter the order ID and upload the invoice; the server reads, screens and shows the chat-style reply. Real WhatsApp plugs in behind the same provider interface later."}
              </p>
            </>
          ) : whatsapp.isError ? (
            <p className="text-sm text-slate-600 dark:text-slate-400">{errorMessage(whatsapp.error)}</p>
          ) : (
            <p className="text-sm text-slate-500">Checking…</p>
          )}
        </Component>
      </div>

      {health.isError && !h && <ErrorState className="mt-6" error={health.error} onRetry={() => void health.refetch()} />}
    </>
  );
}
