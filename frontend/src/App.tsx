import { useCallback, useEffect, useState } from "react";
import { AuthProvider, useAuth, useSession } from "./auth/AuthContext";
import { ConnectionIndicator } from "./components/ConnectionIndicator";
import { FeedPage } from "./components/FeedPage";
import { InsidePage } from "./components/InsidePage";
import { LoginPage } from "./components/LoginPage";
import { MovementLogPage } from "./components/MovementLogPage";
import { VehicleHistoryPage } from "./components/VehicleHistoryPage";
import { secondaryButton } from "./components/Modal";
import { useLiveFeed } from "./feed/useLiveFeed";
import { humanize } from "./lib/format";
import { navigate, useHashRoute, type Page } from "./lib/route";

const NAV: { page: Page; label: string }[] = [
  { page: "feed", label: "Live feed" },
  { page: "inside", label: "Inside campus" },
  { page: "logs", label: "Movement log" },
  { page: "history", label: "Vehicle history" },
];

function SignedInApp() {
  const { token, user } = useSession();
  const { logout } = useAuth();
  // The live stream stays connected while the guard views other pages.
  const { cards, connection, lastSyncAt, upsertItem } = useLiveFeed(token);
  const route = useHashRoute();
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const notify = useCallback((message: string) => setToast(message), []);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <div className="mr-auto">
            <h1 className="text-base font-semibold text-slate-900">Campus gate console</h1>
            <p className="text-xs text-slate-500">Registry and movement context for guards. Guards decide at the gate.</p>
          </div>
          <ConnectionIndicator state={connection} lastSyncAt={lastSyncAt} />
          <div className="flex items-center gap-2 text-xs text-slate-600">
            <span>
              {user.full_name} · {humanize(user.role)}
            </span>
            <button type="button" className={secondaryButton + " px-2 py-1 text-xs"} onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4" aria-label="Pages">
          {NAV.map((n) => (
            <a
              key={n.page}
              href={`#/${n.page}`}
              onClick={(e) => {
                e.preventDefault();
                navigate(n.page);
              }}
              aria-current={route.page === n.page ? "page" : undefined}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
                route.page === n.page ? "border-slate-800 font-medium text-slate-900" : "border-transparent text-slate-600 hover:text-slate-900"
              }`}
            >
              {n.label}
            </a>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-4">
        {route.page === "feed" && (
          <FeedPage token={token} role={user.role} cards={cards} loading={connection === "connecting"} upsertItem={upsertItem} notify={notify} />
        )}
        {route.page === "inside" && <InsidePage token={token} notify={notify} />}
        {route.page === "logs" && <MovementLogPage token={token} notify={notify} />}
        {route.page === "history" && <VehicleHistoryPage token={token} role={user.role} plate={route.param} notify={notify} />}
      </main>

      {toast && (
        <div role="status" className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-md bg-slate-900 px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

function Shell() {
  const { session } = useAuth();
  // Remount per session so a new login starts a fresh stream.
  return session ? <SignedInApp key={session.token} /> : <LoginPage />;
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  );
}
