import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, onUnauthorized } from "../api/client";
import type { UserSummary } from "../api/types";
import { isNativeApp } from "../lib/platform";

interface Session {
  token: string;
  user: UserSummary;
  expiresAt: string;
}

interface AuthState {
  session: Session | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const STORAGE_KEY = "gate-feed-session";
const AuthContext = createContext<AuthState | null>(null);

// Browser: sessionStorage, so the session ends with the tab on shared guard-room machines.
// App: the WebView's private localStorage, so a guard is not signed out on every app restart.
// Either way the token expires after AUTH_TOKEN_TTL_MINUTES.
function store(): Storage | null {
  try {
    return isNativeApp ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function loadSession(): Session | null {
  try {
    const raw = store()?.getItem(STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    return new Date(session.expiresAt).getTime() > Date.now() ? session : null;
  } catch {
    return null;
  }
}

function saveSession(session: Session | null): void {
  try {
    if (session) store()?.setItem(STORAGE_KEY, JSON.stringify(session));
    else store()?.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable (private mode); the session lives in memory only
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);

  const logout = useCallback(() => {
    saveSession(null);
    setSession(null);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    const next = { token: res.access_token, user: res.user, expiresAt: res.expires_at };
    saveSession(next);
    setSession(next);
  }, []);

  useEffect(() => {
    onUnauthorized(logout);
    return () => onUnauthorized(null);
  }, [logout]);

  useEffect(() => {
    if (!session) return;
    const ms = new Date(session.expiresAt).getTime() - Date.now();
    const timer = window.setTimeout(logout, Math.max(0, ms));
    return () => window.clearTimeout(timer);
  }, [session, logout]);

  // Roles are read from the database on every request; pick up a change (or a disabled
  // account, which answers 401 and signs out) when a stored session is resumed.
  const token = session?.token;
  useEffect(() => {
    if (!token) return;
    api
      .me(token)
      .then((user) =>
        setSession((current) => {
          if (!current || current.token !== token) return current;
          const u = current.user;
          if (u.role === user.role && u.full_name === user.full_name && u.username === user.username) return current;
          const next = { ...current, user };
          saveSession(next);
          return next;
        }),
      )
      .catch(() => undefined);
  }, [token]);

  const value = useMemo(() => ({ session, login, logout }), [session, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** For components rendered only after login. */
export function useSession(): Session {
  const { session } = useAuth();
  if (!session) throw new Error("No active session");
  return session;
}
