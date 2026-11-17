import { Car, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useVehicles } from "../api/queries";
import type { VehicleCategory, VehicleStatus } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { ALL_CATEGORIES, VEHICLE_STATUSES } from "../components/forms/options";
import { RegisterVehicleDialog } from "../components/forms/RegisterVehicleDialog";
import { RegistryStatus } from "../components/registry/StatusBadges";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, SkeletonRows } from "../components/ui/Feedback";
import { SearchInput, Select } from "../components/ui/Form";
import { PageHeader, Pagination, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { formatDateTime, humanize } from "../lib/format";
import { useDebounced } from "../lib/hooks";

const PAGE_SIZE = 50;

export function VehiclesPage() {
  const { token, user } = useSession();
  const notify = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [registering, setRegistering] = useState(false);
  const category = (params.get("category") ?? "") as VehicleCategory | "";
  const status = (params.get("status") ?? "") as VehicleStatus | "";
  const skip = Math.max(0, Number(params.get("skip")) || 0);
  const debounced = useDebounced(q.trim(), 300);

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

  const vehicles = useVehicles({ q: debounced || undefined, category: category || undefined, status: status || undefined, skip, limit: PAGE_SIZE });
  const rows = vehicles.data ?? [];

  return (
    <>
      <PageHeader
        title="Vehicles"
        description="The campus registry. A plate is a sensor token; who a vehicle belongs to is recorded on the owner."
        actions={
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setRegistering(true)}>
            Register vehicle
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <SearchInput
          label="Search plates"
          placeholder="Plate fragment, e.g. PB65"
          value={q}
          onChange={(v) => {
            setQ(v);
            set("q", v.trim());
          }}
          className="sm:max-w-xs"
          mono
        />
        <div className="grid grid-cols-2 gap-2 sm:flex">
          <Select value={category} onChange={(e) => set("category", e.target.value)} aria-label="Category" className="sm:w-44">
            <option value="">All categories</option>
            {ALL_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </Select>
          <Select value={status} onChange={(e) => set("status", e.target.value)} aria-label="Registry status" className="sm:w-40">
            <option value="">Any status</option>
            {VEHICLE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <Section bodyClassName="p-0">
        {vehicles.isLoading ? (
          <SkeletonRows rows={8} />
        ) : vehicles.isError ? (
          <ErrorState error={vehicles.error} onRetry={() => void vehicles.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Car className="h-5 w-5" />}
            title={debounced || category || status ? "No vehicles match" : "No vehicles registered"}
            action={
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setRegistering(true)}>
                Register vehicle
              </Button>
            }
          />
        ) : (
          <div className={cx(vehicles.isPlaceholderData && "opacity-60")}>
            <table className="hidden min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800 md:table">
              <thead className="table-head">
                <tr>
                  <th className="px-4 py-2.5">Plate</th>
                  <th className="px-4 py-2.5">Owner</th>
                  <th className="px-4 py-2.5">Category</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Vehicle</th>
                  <th className="px-4 py-2.5">Valid until</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map(({ vehicle: v, owner }) => (
                  <tr
                    key={v.id}
                    className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                    onClick={() => navigate(`/vehicles/${encodeURIComponent(v.plate)}`)}
                  >
                    <td className="px-4 py-3">
                      <Link to={`/vehicles/${encodeURIComponent(v.plate)}`} className="plate text-slate-900 hover:underline dark:text-white" onClick={(e) => e.stopPropagation()}>
                        {v.plate}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                      {owner ? (
                        <>
                          {owner.name}
                          <span className="block text-xs text-slate-500 dark:text-slate-400">{owner.institutional_id}</span>
                        </>
                      ) : (
                        <span className="text-slate-400">No owner</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">{humanize(v.category)}</td>
                    <td className="px-4 py-3">
                      <RegistryStatus status={v.status} />
                      {v.status === "ACTIVE" && !v.is_active && <span className="ml-2 text-xs text-slate-500">outside validity</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-400">{[v.color, v.make_model].filter(Boolean).join(" ") || "—"}</td>
                    <td className="px-4 py-3 text-xs tabular-nums text-slate-600 dark:text-slate-400">{v.valid_until ? formatDateTime(v.valid_until) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800 md:hidden">
              {rows.map(({ vehicle: v, owner }) => (
                <li key={v.id}>
                  <Link to={`/vehicles/${encodeURIComponent(v.plate)}`} className="flex items-center gap-3 px-4 py-3 active:bg-slate-50 dark:active:bg-slate-800/40">
                    <div className="min-w-0 flex-1">
                      <div className="plate text-slate-900 dark:text-white">{v.plate}</div>
                      <div className="truncate text-xs text-slate-500 dark:text-slate-400">
                        {owner ? `${owner.name} · ` : ""}
                        {humanize(v.category)}
                      </div>
                    </div>
                    <RegistryStatus status={v.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <Pagination skip={skip} limit={PAGE_SIZE} count={rows.length} onChange={(s) => set("skip", s ? String(s) : "")} />

      {registering && (
        <RegisterVehicleDialog
          token={token}
          role={user.role}
          onClose={() => setRegistering(false)}
          onRegistered={(message, plate) => {
            setRegistering(false);
            notify(message);
            navigate(`/vehicles/${encodeURIComponent(plate.replace(/[^A-Z0-9]/g, ""))}`);
          }}
        />
      )}
    </>
  );
}
