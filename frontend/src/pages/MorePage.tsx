import { ChevronRight, LogOut } from "lucide-react";
import { Link } from "react-router";
import { visibleNav } from "../app/nav";
import { useAuth, useSession } from "../auth/AuthContext";
import { RoleBadge } from "../components/registry/StatusBadges";
import { Button } from "../components/ui/Button";
import { initials } from "../lib/format";

/** Phone menu for the pages that are not in the tab bar. */
export function MorePage() {
  const { user } = useSession();
  const { logout } = useAuth();
  const items = visibleNav(user.role).filter((i) => !i.tab);
  const groups = [...new Set(items.map((i) => i.group))];

  return (
    <div className="space-y-6">
      <div className="card flex items-center gap-3 p-4">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
          {initials(user.full_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-slate-900 dark:text-white">{user.full_name}</p>
          <p className="truncate font-mono text-xs text-slate-500 dark:text-slate-400">{user.username}</p>
        </div>
        <RoleBadge role={user.role} />
      </div>

      {groups.map((g) => (
        <section key={g}>
          <h2 className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{g}</h2>
          <ul className="card divide-y divide-slate-100 overflow-hidden dark:divide-slate-800">
            {items
              .filter((i) => i.group === g)
              .map((i) => (
                <li key={i.to}>
                  <Link to={i.to} className="flex items-center gap-3 px-4 py-3.5 text-sm font-medium text-slate-800 active:bg-slate-50 dark:text-slate-200 dark:active:bg-slate-800/50">
                    <i.icon className="h-5 w-5 text-slate-500 dark:text-slate-400" aria-hidden />
                    <span className="flex-1">{i.label}</span>
                    <ChevronRight className="h-4 w-4 text-slate-400" aria-hidden />
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      ))}

      <Button className="w-full" icon={<LogOut className="h-4 w-4" />} onClick={logout}>
        Sign out
      </Button>
    </div>
  );
}
