import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useLiveFeed } from "./useLiveFeed";

type LiveFeed = ReturnType<typeof useLiveFeed> & {
  /** Uncertain camera reads no guard has resolved yet (same rule as the dashboard count). */
  needsReview: number;
};

const LiveFeedContext = createContext<LiveFeed | null>(null);

/** One stream per session: it stays connected while the guard moves between pages. */
export function LiveFeedProvider({ token, children }: { token: string; children: ReactNode }) {
  const feed = useLiveFeed(token);
  const needsReview = useMemo(
    () => feed.cards.filter((c) => c.item.link_status === "LOW_CONFIDENCE" && !c.item.resolution).length,
    [feed.cards],
  );
  const value = useMemo(() => ({ ...feed, needsReview }), [feed, needsReview]);
  return <LiveFeedContext.Provider value={value}>{children}</LiveFeedContext.Provider>;
}

export function useFeed(): LiveFeed {
  const ctx = useContext(LiveFeedContext);
  if (!ctx) throw new Error("useFeed must be used inside LiveFeedProvider");
  return ctx;
}
