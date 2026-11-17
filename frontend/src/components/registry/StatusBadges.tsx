import type { LinkStatus } from "../../api/types";
import {
  GATE_STATUS_STYLE,
  LINK_STATUS_HINT,
  LINK_STATUS_LABEL,
  LINK_STATUS_PILL,
  LINK_STATUS_SHORT,
  LINK_STATUS_STYLE,
  humanize,
  registryStatusTone,
} from "../../lib/format";
import { Badge } from "../ui/Feedback";

/** Registry status exactly as recorded (BLACKLISTED is an administrator's record, so it is distinct). */
export function RegistryStatus({ status, prefix = false }: { status: string; prefix?: boolean }) {
  return (
    <Badge className={registryStatusTone(status)} title="Registry status, exactly as recorded">
      {prefix && <span className="font-normal opacity-70">Registry:</span>}
      {status}
    </Badge>
  );
}

export function LinkStatusBadge({ status, short = false }: { status: LinkStatus; short?: boolean }) {
  return (
    <Badge className={LINK_STATUS_STYLE[status].badge} title={LINK_STATUS_HINT[status]}>
      {short ? LINK_STATUS_SHORT[status] : LINK_STATUS_LABEL[status]}
    </Badge>
  );
}

/** LINKED / UNLINKED / NEEDS REVIEW pill for the live plate list. */
export function PlatePill({ status }: { status: LinkStatus }) {
  return (
    <Badge className={`${LINK_STATUS_STYLE[status].badge} tracking-wide`} title={LINK_STATUS_HINT[status]}>
      {LINK_STATUS_PILL[status]}
    </Badge>
  );
}

export function GateStatusBadge({ status }: { status: string }) {
  return <Badge className={GATE_STATUS_STYLE[status] ?? GATE_STATUS_STYLE.OFFLINE}>{humanize(status)}</Badge>;
}

export function RoleBadge({ role }: { role: string }) {
  const tone =
    role === "ADMIN"
      ? "bg-slate-900 text-white ring-slate-900 dark:bg-slate-100 dark:text-slate-900 dark:ring-slate-100"
      : role === "SUPERVISOR"
        ? "bg-sky-50 text-sky-900 ring-sky-300 dark:bg-sky-500/15 dark:text-sky-200 dark:ring-sky-500/40"
        : "bg-slate-100 text-slate-700 ring-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-600";
  return <Badge className={tone}>{humanize(role)}</Badge>;
}
