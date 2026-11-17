import { CheckCircle2, ChevronDown, Server, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { LogoMark } from "../components/brand/Logo";
import { Button } from "../components/ui/Button";
import { ErrorNote } from "../components/ui/Feedback";
import { Field, Input, PasswordInput } from "../components/ui/Form";
import { cx } from "../lib/cx";
import { apiBase, isNativeApp, normalizeServerUrl, saveServerUrl, serverConfigured, storedServerUrl } from "../lib/platform";

export function ServerSettings({ onSaved, compact = false }: { onSaved?: () => void; compact?: boolean }) {
  const [value, setValue] = useState(storedServerUrl() ?? (apiBase() !== "/api" ? apiBase() : ""));
  const [state, setState] = useState<{ kind: "idle" | "testing" | "ok" | "error"; message?: string }>({ kind: "idle" });

  const test = async (e?: FormEvent) => {
    e?.preventDefault();
    const url = normalizeServerUrl(value);
    if (!url) {
      setState({ kind: "error", message: "Enter an address like http://192.168.1.20:8000" });
      return;
    }
    setState({ kind: "testing" });
    try {
      await api.health(url);
      saveServerUrl(url);
      setValue(url);
      setState({ kind: "ok", message: "Connected. This address is saved on this device." });
      onSaved?.();
    } catch (err) {
      setState({ kind: "error", message: err instanceof ApiError ? `${err.message} (${url})` : `Could not reach ${url}.` });
    }
  };

  const reset = () => {
    saveServerUrl(null);
    setValue("");
    setState({ kind: "idle" });
    onSaved?.();
  };

  return (
    <form onSubmit={test} className="space-y-3">
      <Field
        label="Server address"
        hint={isNativeApp ? "The address of the campus console backend, e.g. http://192.168.1.20:8000" : "Leave empty to use this site's /api proxy."}
      >
        <Input
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setState({ kind: "idle" });
          }}
          placeholder="http://192.168.1.20:8000"
          inputMode="url"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          className="font-mono"
        />
      </Field>
      <div className={cx("flex gap-2", compact ? "flex-row" : "flex-col sm:flex-row")}>
        <Button type="submit" loading={state.kind === "testing"} icon={<Server className="h-4 w-4" />} disabled={!value.trim()}>
          Test & save
        </Button>
        {!isNativeApp && storedServerUrl() && (
          <Button variant="ghost" onClick={reset}>
            Use this site's /api
          </Button>
        )}
      </div>
      {state.kind === "ok" && (
        <p className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300" role="status">
          <CheckCircle2 className="h-4 w-4 text-sky-600 dark:text-sky-400" aria-hidden />
          {state.message}
        </p>
      )}
      {state.kind === "error" && <ErrorNote message={state.message ?? "Connection failed."} />}
    </form>
  );
}

export function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [configured, setConfigured] = useState(serverConfigured());
  const [showServer, setShowServer] = useState(isNativeApp && !serverConfigured());

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!serverConfigured()) {
      setShowServer(true);
      setError("Set the server address first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-dvh flex-col bg-slate-100 px-4 pb-safe pt-safe dark:bg-slate-950">
      <div className="m-auto w-full max-w-sm py-10">
        <div className="mb-8 flex flex-col items-center text-center">
          <LogoMark className="h-12 w-12" />
          <h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-900 dark:text-white">Gate Console</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">Campus vehicle security · sign in with your guard, supervisor or admin account</p>
        </div>

        <div className="card p-6">
          <form onSubmit={submit} className="space-y-4">
            <Field label="Username">
              <Input autoComplete="username" autoCapitalize="none" autoCorrect="off" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </Field>
            <Field label="Password">
              <PasswordInput autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            <ErrorNote message={error} />
            <Button type="submit" variant="primary" className="w-full py-2.5" loading={submitting} disabled={!configured}>
              Sign in
            </Button>
          </form>

          <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-800">
            <button
              type="button"
              className="flex w-full items-center justify-between text-left text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
              aria-expanded={showServer}
              onClick={() => setShowServer((s) => !s)}
            >
              <span className="inline-flex items-center gap-1.5">
                <Server className="h-3.5 w-3.5" aria-hidden />
                Connection settings
                {!configured && <span className="font-semibold text-slate-900 dark:text-white">· required</span>}
              </span>
              <ChevronDown className={cx("h-4 w-4 transition-transform", showServer && "rotate-180")} aria-hidden />
            </button>
            {showServer && (
              <div className="mt-3">
                <ServerSettings onSaved={() => setConfigured(serverConfigured())} />
              </div>
            )}
          </div>
        </div>

        <p className="mt-6 flex items-start justify-center gap-2 text-center text-xs text-slate-500 dark:text-slate-400">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Shows registry and movement context only. Guards decide at the gate.
        </p>
      </div>
    </main>
  );
}
