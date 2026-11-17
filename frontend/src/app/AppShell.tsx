import { LogOut, Menu as MenuIcon, Moon, Search, Sun } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useAlerts } from "../api/queries";
import { useAuth, useSession } from "../auth/AuthContext";
import { LogoMark, Logo } from "../components/brand/Logo";
import { ConnectionIndicator } from "../components/feed/ConnectionIndicator";
import { RoleBadge } from "../components/registry/StatusBadges";
import { IconButton } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { SearchInput } from "../components/ui/Form";
import { useFeed } from "../feed/LiveFeedContext";
import { cx } from "../lib/cx";
import { initials } from "../lib/format";
import { useTheme } from "../lib/theme";
import { NAV, normalizePlate, visibleNav, type NavItem } from "./nav";

function Badge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto min-w-5 rounded-full bg-amber-100 px-1.5 text-center text-[11px] font-semibold tabular-nums text-amber-900 ring-1 ring-amber-300 dark:bg-amber-500/20 dark:text-amber-200 dark:ring-amber-500/40">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function SidebarLink({ item, badges }: { item: NavItem; badges: Record<string, number> }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cx(
          "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          isActive
            ? "bg-slate-900 text-white dark:bg-slate-800 dark:text-white"
            : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-white",
        )
      }
    >
      <item.icon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="truncate">{item.label}</span>
      <Badge count={badges[item.to] ?? 0} />
    </NavLink>
  );
}

function PlateSearch({ onDone, autoFocus = false, inputRef }: { onDone?: () => void; autoFocus?: boolean; inputRef?: RefObject<HTMLFormElement | null> }) {
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const plate = normalizePlate(value);
    if (!plate) return;
    navigate(`/vehicles/${encodeURIComponent(plate)}`);
    setValue("");
    onDone?.();
  };
  return (
    <form ref={inputRef} onSubmit={submit} role="search" className="w-full">
      <SearchInput label="Look up a plate" placeholder="Look up a plate…  ( / )" value={value} onChange={setValue} autoFocus={autoFocus} mono />
    </form>
  );
}

export function AppShell() {
  const { user } = useSession();
  const { logout } = useAuth();
  const { connection, lastSyncAt, needsReview } = useFeed();
  const alerts = useAlerts(100, 30_000);
  const badges: Record<string, number> = {
    "/feed": needsReview,
    "/reviews": needsReview,
    "/alerts": alerts.data?.length ?? 0,
  };
  const { resolved, setPreference } = useTheme();
  const location = useLocation();
  const [searchOpen, setSearchOpen] = useState(false);
  const searchForm = useRef<HTMLFormElement>(null);

  const items = visibleNav(user.role);
  const groups = [...new Set(items.map((i) => i.group))];
  const tabs = items.filter((i) => i.tab);
  const current =
    NAV.find((n) => (n.end ? location.pathname === n.to : location.pathname === n.to || location.pathname.startsWith(`${n.to}/`))) ??
    (location.pathname === "/more" ? { label: "More" } : null);

  // "/" focuses the plate search (desktop), like most consoles
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || target.closest("input,textarea,select,[contenteditable]")) return;
      const input = searchForm.current?.querySelector("input");
      if (input && input.offsetParent !== null) {
        e.preventDefault();
        input.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  const toggleTheme = () => setPreference(resolved === "dark" ? "light" : "dark");

  return (
    <div className="min-h-dvh lg:pl-64">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:flex">
        <div className="flex h-16 shrink-0 items-center px-5">
          <Link to="/" className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
            <Logo />
          </Link>
        </div>
        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-2" aria-label="Main">
          {groups.map((g) => (
            <div key={g}>
              <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">{g}</p>
              <div className="space-y-0.5">
                {items
                  .filter((i) => i.group === g)
                  .map((i) => (
                    <SidebarLink key={i.to} item={i} badges={badges} />
                  ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3 dark:border-slate-800">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {initials(user.full_name)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{user.full_name}</p>
              <div className="mt-0.5">
                <RoleBadge role={user.role} />
              </div>
            </div>
            <IconButton label="Sign out" icon={<LogOut className="h-4 w-4" />} onClick={logout} />
          </div>
        </div>
      </aside>

      {/* Top bar with Navigation Tabs */}
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 pt-safe backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/95">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6 lg:h-16 lg:px-8">
          <Link to="/" className="flex items-center gap-2.5 lg:hidden" aria-label="Overview">
            <LogoMark className="h-7 w-7" />
            <span className="text-sm font-semibold text-slate-900 dark:text-white">{current?.label ?? "Gate Console"}</span>
          </Link>
          <div className="hidden max-w-xs flex-1 lg:block">
            <PlateSearch inputRef={searchForm} />
          </div>

          {/* Desktop Navigation Tabs for Guard Operations */}
          <nav className="hidden items-center gap-1 xl:flex" aria-label="Quick operations">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.end}
                className={({ isActive }) =>
                  cx(
                    "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
                    isActive
                      ? "bg-slate-900 text-white dark:bg-slate-800 dark:text-white"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-white",
                  )
                }
              >
                <t.icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span>{t.short ?? t.label}</span>
                {(badges[t.to] ?? 0) > 0 && (
                  <span className="ml-1 rounded-full bg-amber-400/90 px-1 text-[10px] font-bold text-slate-900">
                    {badges[t.to]}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1.5">
            <ConnectionIndicator state={connection} lastSyncAt={lastSyncAt} compact />
            <IconButton className="lg:hidden" label="Look up a plate" icon={<Search className="h-5 w-5" />} onClick={() => setSearchOpen(true)} />
            <IconButton
              label={resolved === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              icon={resolved === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
              onClick={toggleTheme}
            />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-5 sm:px-6 lg:px-8 lg:pb-12 lg:pt-7">
        <Outlet />
      </main>

      {/* Phone tab bar with all 6 operational tabs + More */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 pb-safe backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/95 lg:hidden"
        aria-label="Main"
      >
        <div className="mx-auto grid max-w-2xl grid-cols-7">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                cx(
                  "relative flex flex-col items-center gap-0.5 py-1.5 text-[10px] font-medium",
                  isActive ? "text-slate-900 dark:text-white" : "text-slate-500 dark:text-slate-400",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span className={cx("flex h-6 w-10 items-center justify-center rounded-full transition-colors", isActive && "bg-slate-100 dark:bg-slate-800")}>
                    <t.icon className="h-4 w-4" aria-hidden />
                  </span>
                  <span className="truncate">{t.short ?? t.label}</span>
                  {(badges[t.to] ?? 0) > 0 && (
                    <span className="absolute right-[15%] top-1 h-2 w-2 rounded-full bg-amber-400 ring-2 ring-white dark:ring-slate-900" aria-label="Needs attention" />
                  )}
                </>
              )}
            </NavLink>
          ))}
          <NavLink
            to="/more"
            className={({ isActive }) =>
              cx("flex flex-col items-center gap-0.5 py-1.5 text-[10px] font-medium", isActive ? "text-slate-900 dark:text-white" : "text-slate-500 dark:text-slate-400")
            }
          >
            {({ isActive }) => (
              <>
                <span className={cx("flex h-6 w-10 items-center justify-center rounded-full transition-colors", isActive && "bg-slate-100 dark:bg-slate-800")}>
                  <MenuIcon className="h-4 w-4" aria-hidden />
                </span>
                More
              </>
            )}
          </NavLink>
        </div>
      </nav>

      {searchOpen && (
        <Dialog title="Look up a plate" description="Movements and sightings across all gates, with registry details." onClose={() => setSearchOpen(false)} size="sm">
          <PlateSearch autoFocus onDone={() => setSearchOpen(false)} />
        </Dialog>
      )}
    </div>
  );
}
