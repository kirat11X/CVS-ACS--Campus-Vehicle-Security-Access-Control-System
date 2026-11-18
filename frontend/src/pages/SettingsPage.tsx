import { LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import { useAuth, useSession } from "../auth/AuthContext";
import { RoleBadge } from "../components/registry/StatusBadges";
import { Button } from "../components/ui/Button";
import { ErrorNote } from "../components/ui/Feedback";
import { ChoiceGroup, Field, PasswordInput } from "../components/ui/Form";
import { Detail, DetailList, PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { describeServer, isNativeApp, platformName } from "../lib/platform";
import { humanize } from "../lib/format";
import { useTheme, type ThemePreference } from "../lib/theme";
import { ServerSettings } from "./LoginPage";
import { GateCamerasSection } from "../components/settings/GateCamerasSection";

function ChangePassword() {
  const { token } = useSession();
  const notify = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mismatch = confirm.length > 0 && confirm !== next;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== confirm) return;
    setBusy(true);
    setError(null);
    try {
      await api.changePassword(token, { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setConfirm("");
      notify("Password changed.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="grid max-w-xl grid-cols-1 gap-4 sm:grid-cols-2">
      <Field label="Current password" className="sm:col-span-2">
        <PasswordInput autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </Field>
      <Field label="New password" hint="At least 8 characters.">
        <PasswordInput autoComplete="new-password" value={next} minLength={8} onChange={(e) => setNext(e.target.value)} required />
      </Field>
      <Field label="Repeat new password" error={mismatch ? "Passwords do not match." : null}>
        <PasswordInput autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
      </Field>
      <div className="sm:col-span-2">
        <ErrorNote message={error} />
      </div>
      <div className="sm:col-span-2">
        <Button type="submit" variant="primary" loading={busy} disabled={!current || next.length < 8 || next !== confirm}>
          Change password
        </Button>
      </div>
    </form>
  );
}

export function SettingsPage() {
  const { user } = useSession();
  const { logout } = useAuth();
  const { preference, setPreference } = useTheme();

  return (
    <>
      <PageHeader title="Settings" />
      <div className="space-y-6">
        <Section title="Profile">
          <DetailList>
            <Detail label="Name" value={user.full_name} />
            <Detail label="Username" value={user.username} mono />
            <Detail label="Role" value={<RoleBadge role={user.role} />} />
          </DetailList>
        </Section>

        <Section title="Appearance" description="Dark mode suits a guard room at night. System follows the device setting.">
          <div className="max-w-md">
            <ChoiceGroup<ThemePreference>
              legend="Theme"
              value={preference}
              onChange={setPreference}
              options={[
                { value: "light", label: "Light", icon: <Sun className="h-4 w-4" /> },
                { value: "dark", label: "Dark", icon: <Moon className="h-4 w-4" /> },
                { value: "system", label: "System", icon: <Monitor className="h-4 w-4" /> },
              ]}
            />
          </div>
        </Section>

        <GateCamerasSection />

        <Section title="Password">
          <ChangePassword />
        </Section>

        <Section title="Server connection" description={`Requests currently go to ${describeServer()}.`}>
          <div className="max-w-xl">
            <ServerSettings onSaved={() => window.location.reload()} compact />
          </div>
        </Section>

        <Section title="About">
          <DetailList>
            <Detail label="Version" value={`v${__APP_VERSION__}`} />
            <Detail label="Platform" value={isNativeApp ? `${humanize(platformName)} app` : "Web browser"} />
            <Detail label="Session storage" value={isNativeApp ? "This device until the token expires" : "This browser tab"} />
          </DetailList>
          <p className="mt-4 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            The console shows what cameras and guards observed, how it links to the registry, and the movement record. It never opens or closes a barrier and makes no
            access decision: guards decide at the gate.
          </p>
        </Section>

        <Button icon={<LogOut className="h-4 w-4" />} onClick={logout}>
          Sign out
        </Button>
      </div>
    </>
  );
}
