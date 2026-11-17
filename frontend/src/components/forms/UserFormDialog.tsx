import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { useInvalidate } from "../../api/queries";
import type { Role, UserAccount, UserUpdate } from "../../api/types";
import { humanize } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { ErrorNote } from "../ui/Feedback";
import { Field, Input, PasswordInput, Select, Switch } from "../ui/Form";
import { ROLES } from "./options";

const ROLE_HINT: Record<Role, string> = {
  GUARD: "Live feed, manual entries, confirmations, visitor and delivery registrations.",
  SUPERVISOR: "Same actions as a guard; for shift leads.",
  ADMIN: "Everything, including registry edits, gates, lanes and accounts.",
};

/** Create (user = null) or edit an account. ADMIN only. Accounts are disabled, never deleted. */
export function UserFormDialog({
  token,
  user,
  selfId,
  onClose,
  onSaved,
}: {
  token: string;
  user: UserAccount | null;
  selfId: string;
  onClose: () => void;
  onSaved: (m: string) => void;
}) {
  const invalidate = useInvalidate();
  const isSelf = user?.id === selfId;
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "GUARD");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (user) {
        const body: UserUpdate = {};
        if (fullName.trim() !== user.full_name) body.full_name = fullName.trim();
        if (email.trim() !== user.email) body.email = email.trim();
        if (role !== user.role) body.role = role;
        if (active !== user.is_active) body.is_active = active;
        if (password) body.password = password;
        if (Object.keys(body).length) await api.updateUser(token, user.id, body);
      } else {
        await api.createUser(token, { username: username.trim(), full_name: fullName.trim(), email: email.trim(), role, password });
      }
      void invalidate("users");
      onSaved(user ? `Updated ${user.username}.` : `Created ${username.trim()} (${humanize(role)}).`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the account.");
    } finally {
      setSubmitting(false);
    }
  };

  const passwordShort = password.length > 0 && password.length < 8;

  return (
    <Dialog
      title={user ? `Account · ${user.username}` : "New account"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            form="user-form"
            variant="primary"
            loading={submitting}
            disabled={!fullName.trim() || !email.trim() || (!user && (!username.trim() || password.length < 8)) || passwordShort}
          >
            {user ? "Save changes" : "Create account"}
          </Button>
        </>
      }
    >
      <form id="user-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Username" hint={user ? "Cannot be changed." : "Letters, digits, . _ -"}>
            <Input
              value={username}
              maxLength={50}
              required
              disabled={!!user}
              autoCapitalize="none"
              autoComplete="off"
              pattern="[A-Za-z0-9_.\-]{3,50}"
              onChange={(e) => setUsername(e.target.value)}
            />
          </Field>
          <Field label="Full name">
            <Input value={fullName} maxLength={100} required onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Email">
            <Input type="email" value={email} maxLength={120} required onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Role" hint={isSelf ? "You cannot change your own role." : ROLE_HINT[role]}>
            <Select value={role} disabled={isSelf} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {humanize(r)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label={user ? "Reset password (optional)" : "Password"} hint="At least 8 characters." error={passwordShort ? "Use at least 8 characters." : null}>
          <PasswordInput value={password} maxLength={256} required={!user} autoComplete="new-password" onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {user && (
          <Switch
            checked={active}
            onChange={setActive}
            disabled={isSelf}
            label="Can sign in"
            description={isSelf ? "You cannot disable your own account." : "Disabling takes effect immediately, including open sessions. The account and its audit history are kept."}
          />
        )}
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
