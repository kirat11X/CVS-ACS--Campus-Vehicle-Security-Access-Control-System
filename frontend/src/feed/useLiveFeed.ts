import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, api, notifyUnauthorized } from "../api/client";
import type { FeedEntry, FeedKind, ResolvedObservation } from "../api/types";
import { readEventStream } from "./sse";

/** live: SSE connected · reconnecting: SSE retrying · polling: SSE unavailable, polling works · offline: nothing works */
export type ConnectionState = "connecting" | "live" | "reconnecting" | "polling" | "offline";

export interface FeedCard {
  item: ResolvedObservation;
  kind: FeedKind;
  receivedAt: number;
}

const MAX_CARDS = 200;
const POLL_INTERVAL_MS = 3000;
const SSE_FAILURES_BEFORE_POLLING = 2;
const STREAM_SILENCE_TIMEOUT_MS = 40_000; // server sends keep-alives every 15 s

class FatalStreamError extends Error {}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      window.clearTimeout(timer);
      resolve();
    });
  });
}

const observedAt = (card: FeedCard) => Date.parse(card.item.observation.observed_at);

function upsert(prev: Map<string, FeedCard>, entries: FeedEntry[]): Map<string, FeedCard> {
  if (entries.length === 0) return prev;
  const next = new Map(prev);
  const now = Date.now();
  for (const entry of entries) {
    // Keyed by observation id: a Frigate refinement of the same source_event_id
    // replaces the existing card instead of adding a new one.
    next.set(entry.item.observation.id, { item: entry.item, kind: entry.kind, receivedAt: now });
  }
  if (next.size > MAX_CARDS) {
    const oldest = [...next.values()]
      .sort((a, b) => observedAt(a) - observedAt(b))
      .slice(0, next.size - MAX_CARDS);
    for (const card of oldest) next.delete(card.item.observation.id);
  }
  return next;
}

export function useLiveFeed(token: string) {
  const [cards, setCards] = useState<Map<string, FeedCard>>(() => new Map());
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let cursor: number | null = null;
    let sseFailures = 0;
    let pollTimer: number | null = null;
    let streamLive = false;

    const apply = (entries: FeedEntry[], nextCursor: number) => {
      cursor = cursor === null ? nextCursor : Math.max(cursor, nextCursor);
      setCards((prev) => upsert(prev, entries));
      setLastSyncAt(Date.now());
    };

    const loadSnapshot = async () => {
      const page = await api.feed(token, undefined, signal);
      cursor = page.cursor;
      setCards(upsert(new Map(), page.entries));
      setLastSyncAt(Date.now());
    };

    const pollOnce = async () => {
      try {
        if (cursor === null) await loadSnapshot();
        let page;
        do {
          page = await api.feed(token, cursor ?? 0, signal);
          apply(page.entries, page.cursor);
        } while (page.has_more && !signal.aborted);
        if (!streamLive) setConnection("polling");
      } catch {
        if (!signal.aborted && !streamLive) setConnection("offline");
      }
    };

    const startPolling = () => {
      if (pollTimer !== null) return;
      void pollOnce();
      pollTimer = window.setInterval(() => void pollOnce(), POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (pollTimer !== null) window.clearInterval(pollTimer);
      pollTimer = null;
    };

    const runStream = async () => {
      const streamController = new AbortController();
      const abortStream = () => streamController.abort();
      signal.addEventListener("abort", abortStream);
      let silenceTimer = window.setTimeout(abortStream, STREAM_SILENCE_TIMEOUT_MS);
      const onActivity = () => {
        window.clearTimeout(silenceTimer);
        silenceTimer = window.setTimeout(abortStream, STREAM_SILENCE_TIMEOUT_MS);
      };
      try {
        const res = await fetch(`${API_BASE}/feed/stream?since_id=${cursor ?? 0}`, {
          headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
          signal: streamController.signal,
          cache: "no-store",
        });
        if (res.status === 401) {
          notifyUnauthorized();
          throw new FatalStreamError("Session expired");
        }
        if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`);
        await readEventStream(
          res.body,
          (msg) => {
            if (msg.event === "ready") {
              streamLive = true;
              sseFailures = 0;
              stopPolling();
              setConnection("live");
              setLastSyncAt(Date.now());
            } else if (msg.event === "feed") {
              const entry = JSON.parse(msg.data) as FeedEntry;
              apply([entry], entry.cursor);
            }
          },
          onActivity,
        );
      } finally {
        streamLive = false;
        window.clearTimeout(silenceTimer);
        signal.removeEventListener("abort", abortStream);
      }
    };

    const loop = async () => {
      while (!signal.aborted) {
        try {
          if (cursor === null) await loadSnapshot();
          await runStream();
          sseFailures += 1; // server closed the stream
        } catch (err) {
          if (signal.aborted || err instanceof FatalStreamError) return;
          sseFailures += 1;
        }
        if (signal.aborted) return;
        if (sseFailures >= SSE_FAILURES_BEFORE_POLLING) startPolling();
        else setConnection("reconnecting");
        await sleep(Math.min(15_000, 1000 * 2 ** Math.min(sseFailures - 1, 4)), signal);
      }
    };

    void loop();
    return () => {
      controller.abort();
      stopPolling();
    };
  }, [token]);

  /** Apply a response from one of our own actions without waiting for the stream. */
  const upsertItem = useCallback((item: ResolvedObservation, kind: FeedKind) => {
    setCards((prev) => upsert(prev, [{ item, kind, cursor: 0 }]));
  }, []);

  const sorted = useMemo(
    () => [...cards.values()].sort((a, b) => observedAt(b) - observedAt(a)),
    [cards],
  );

  return { cards: sorted, connection, lastSyncAt, upsertItem };
}
