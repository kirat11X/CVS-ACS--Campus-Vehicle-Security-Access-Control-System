import { Pencil, Plus, UserCog } from "lucide-react";
import { useState } from "react";
import { useUsers } from "../api/queries";
import type { Role, UserAccount } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { ROLES } from "../components/forms/options";
import { UserFormDialog } from "../components/forms/UserFormDialog";
import { RoleBadge } from "../components/registry/StatusBadges";
import { Button } from "../components/ui/Button";
import { Badge, EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { SearchInput, Select } from "../components/ui/Form";
import { FilterChips, PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { formatDate, humanize, initials } from "../lib/format";
import { useDebounced } from "../lib/hooks";

type ActiveFilter = "active" | "disabled" | "all";

export function UsersPage() {
  const { token, user } = useSession();
  const notify = useToast();
  const [q, setQ] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [active, setActive] = useState<ActiveFilter>("active");
  const [editing, setEditing] = useState<UserAccount | null | "new">(null);
  const debounced = useDebounced(q.trim(), 300);

  const users = useUsers({
    q: debounced || undefined,
    role: role || undefined,
    is_active: active === "all" ? undefined : active === "active",
    limit: 200,
  });
  const rows = users.data ?? [];

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Console sign-ins for guards, supervisors and administrators. Accounts are disabled, never deleted, so audit records keep their author."
        actions={
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>
            New account
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput label="Search accounts" placeholder="Username, name or email" value={q} onChange={setQ} className="sm:max-w-xs" />
        <Select value={role} onChange={(e) => setRole(e.target.value as Role | "")} aria-label="Role" className="sm:w-40">
          <option value="">All roles</option>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {humanize(r)}
            </option>
          ))}
        </Select>
        <FilterChips<ActiveFilter>
          label="Account state"
          value={active}
          onChange={setActive}
          options={[
            { value: "active", label: "Can sign in" },
            { value: "disabled", label: "Disabled" },
            { value: "all", label: "All" },
          ]}
        />
      </div>

      <Section bodyClassName="p-0">
        {users.isLoading ? (
          <SkeletonRows rows={6} />
        ) : users.isError ? (
          <ErrorState error={users.error} onRetry={() => void users.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState icon={<UserCog className="h-5 w-5" />} title="No accounts match" />
        ) : (
          <ul className={cx("divide-y divide-slate-100 dark:divide-slate-800", users.isPlaceholderData && "opacity-60")}>
            {rows.map((u) => (
              <li key={u.id} className={cx("flex items-center gap-3 px-4 py-3 sm:px-5", !u.is_active && "opacity-60")}>
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  {initials(u.full_name)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900 dark:text-white">
                    {u.full_name}
                    {u.id === user.id && <span className="text-xs font-normal text-slate-500">(you)</span>}
                  </p>
                  <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                    <span className="font-mono">{u.username}</span> · {u.email} · since {formatDate(u.created_at)}
                  </p>
                </div>
                <div className="hidden items-center gap-2 sm:flex">
                  {!u.is_active && <Badge className="bg-zinc-100 text-zinc-600 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700">Disabled</Badge>}
                  <RoleBadge role={u.role} />
                </div>
                <Button size="sm" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(u)} aria-label={`Edit ${u.username}`}>
                  <span className="hidden sm:inline">Edit</span>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {editing && (
        <UserFormDialog
          token={token}
          user={editing === "new" ? null : editing}
          selfId={user.id}
          onClose={() => setEditing(null)}
          onSaved={(m) => {
            setEditing(null);
            notify(m);
          }}
        />
      )}
    </>
  );
}
