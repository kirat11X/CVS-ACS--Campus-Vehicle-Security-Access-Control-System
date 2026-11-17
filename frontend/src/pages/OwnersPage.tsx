import { Plus, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useOwners } from "../api/queries";
import type { PersonType, ResidenceType } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { OwnerFormDialog } from "../components/forms/OwnerFormDialog";
import { PERSON_TYPES, RESIDENCE_TYPES } from "../components/forms/options";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { SearchInput, Select } from "../components/ui/Form";
import { PageHeader, Pagination, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { humanize, initials } from "../lib/format";
import { useDebounced } from "../lib/hooks";

const PAGE_SIZE = 50;

export function OwnersPage() {
  const { token, user } = useSession();
  const notify = useToast();
  const navigate = useNavigate();
  const isAdmin = user.role === "ADMIN";
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [creating, setCreating] = useState(false);
  const personType = (params.get("person_type") ?? "") as PersonType | "";
  const residenceType = (params.get("residence_type") ?? "") as ResidenceType | "";
  const skip = Math.max(0, Number(params.get("skip")) || 0);
  const debounced = useDebounced(q.trim(), 300);
  const search = debounced.length >= 2 ? debounced : undefined;

  const set = (key: string, value: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value) next.set(key, value);
        else next.delete(key);
        if (key !== "skip") next.delete("skip");
        return next;
      },
      { replace: true },
    );

  const owners = useOwners({ q: search, person_type: personType || undefined, residence_type: residenceType || undefined, skip, limit: PAGE_SIZE });
  const rows = owners.data ?? [];

  return (
    <>
      <PageHeader
        title="Owners"
        description="Institutional identities. Residence (hostel block, day scholar, off campus) belongs to the person and applies to all of their vehicles."
        actions={
          isAdmin && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              New owner
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <SearchInput
          label="Search owners"
          placeholder="Name, ID, phone or email"
          value={q}
          onChange={(v) => {
            setQ(v);
            set("q", v.trim());
          }}
          className="sm:max-w-xs"
        />
        <div className="grid grid-cols-2 gap-2 sm:flex">
          <Select value={personType} onChange={(e) => set("person_type", e.target.value)} aria-label="Person type" className="sm:w-40">
            <option value="">All people</option>
            {PERSON_TYPES.map((p) => (
              <option key={p} value={p}>
                {humanize(p)}
              </option>
            ))}
          </Select>
          <Select value={residenceType} onChange={(e) => set("residence_type", e.target.value)} aria-label="Residence type" className="sm:w-44">
            <option value="">Any residence</option>
            {RESIDENCE_TYPES.map((r) => (
              <option key={r} value={r}>
                {humanize(r)}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {q.trim().length === 1 && <p className="hint -mt-2 mb-3">Type at least 2 characters to search.</p>}

      <Section bodyClassName="p-0">
        {owners.isLoading ? (
          <SkeletonRows rows={8} />
        ) : owners.isError ? (
          <ErrorState error={owners.error} onRetry={() => void owners.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState icon={<Users className="h-5 w-5" />} title={search || personType || residenceType ? "No owners match" : "No owners recorded"} />
        ) : (
          <ul className={cx("divide-y divide-slate-100 dark:divide-slate-800", owners.isPlaceholderData && "opacity-60")}>
            {rows.map((o) => (
              <li key={o.id}>
                <Link to={`/owners/${o.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 active:bg-slate-50 dark:hover:bg-slate-800/40 sm:px-5">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                    {initials(o.name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-slate-900 dark:text-white">{o.name}</span>
                    <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
                      {o.institutional_id} · {humanize(o.person_type)}
                      {o.department ? ` · ${o.department}` : ""}
                    </span>
                  </span>
                  <span className="hidden text-right text-xs text-slate-600 dark:text-slate-400 sm:block">
                    {humanize(o.residence_type)}
                    {o.residence && <span className="block text-slate-500">{o.residence}</span>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Pagination skip={skip} limit={PAGE_SIZE} count={rows.length} onChange={(s) => set("skip", s ? String(s) : "")} />

      {creating && (
        <OwnerFormDialog
          token={token}
          owner={null}
          onClose={() => setCreating(false)}
          onSaved={(o) => {
            setCreating(false);
            notify(`Added ${o.name}.`);
            navigate(`/owners/${o.id}`);
          }}
        />
      )}
    </>
  );
}
