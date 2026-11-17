import { Car, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { useOwner } from "../api/queries";
import { useSession } from "../auth/AuthContext";
import { OwnerFormDialog } from "../components/forms/OwnerFormDialog";
import { RegisterVehicleDialog } from "../components/forms/RegisterVehicleDialog";
import { RegistryStatus } from "../components/registry/StatusBadges";
import { Button } from "../components/ui/Button";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/Feedback";
import { Detail, DetailList, PageHeader, Section } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { formatDateTime, humanize } from "../lib/format";

export function OwnerDetailPage() {
  const { id } = useParams();
  const { token, user } = useSession();
  const notify = useToast();
  const isAdmin = user.role === "ADMIN";
  const owner = useOwner(id ?? null);
  const [dialog, setDialog] = useState<"edit" | "register" | null>(null);
  const o = owner.data?.owner;
  const vehicles = owner.data?.vehicles ?? [];

  return (
    <>
      <PageHeader
        back={{ to: "/owners", label: "Owners" }}
        title={o?.name ?? (owner.isLoading ? "Loading…" : "Owner")}
        description={o ? `${o.institutional_id} · ${humanize(o.person_type)}${o.department ? ` · ${o.department}` : ""}` : undefined}
        actions={
          o && (
            <>
              <Button icon={<Plus className="h-4 w-4" />} onClick={() => setDialog("register")}>
                Register vehicle
              </Button>
              {isAdmin && (
                <Button variant="primary" icon={<Pencil className="h-4 w-4" />} onClick={() => setDialog("edit")}>
                  Edit
                </Button>
              )}
            </>
          )
        }
      />

      {owner.isLoading ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : owner.isError ? (
        <div className="card">
          <ErrorState error={owner.error} onRetry={() => void owner.refetch()} />
        </div>
      ) : (
        o && (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Section title="Person" className="lg:col-span-1">
              <DetailList className="sm:grid-cols-2 lg:grid-cols-1">
                <Detail label="Institutional ID" value={o.institutional_id} mono />
                <Detail label="Person type" value={humanize(o.person_type)} />
                <Detail label="Residence" value={humanize(o.residence_type)} />
                <Detail label="Block / address" value={o.residence} />
                <Detail label="Department" value={o.department} />
                <Detail label="Phone" value={o.phone} />
                <Detail label="Email" value={o.email} />
                <Detail label="Record status" value={o.status} />
              </DetailList>
            </Section>

            <Section className="lg:col-span-2" title={`Vehicles (${vehicles.length})`} bodyClassName="p-0">
              {vehicles.length === 0 ? (
                <EmptyState
                  icon={<Car className="h-5 w-5" />}
                  title="No vehicles registered to this person"
                  action={
                    <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setDialog("register")}>
                      Register vehicle
                    </Button>
                  }
                />
              ) : (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {vehicles.map(({ vehicle: v }) => (
                    <li key={v.id}>
                      <Link to={`/vehicles/${encodeURIComponent(v.plate)}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/40 sm:px-5">
                        <span className="plate text-slate-900 dark:text-white">{v.plate}</span>
                        <span className="text-xs text-slate-600 dark:text-slate-400">{humanize(v.category)}</span>
                        <span className="text-xs text-slate-500 dark:text-slate-400">{[v.color, v.make_model].filter(Boolean).join(" ")}</span>
                        <span className="ml-auto flex items-center gap-2">
                          {v.valid_until && <span className="text-xs text-slate-500 dark:text-slate-400">until {formatDateTime(v.valid_until)}</span>}
                          <RegistryStatus status={v.status} />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        )
      )}

      {dialog === "edit" && o && (
        <OwnerFormDialog
          token={token}
          owner={o}
          onClose={() => setDialog(null)}
          onSaved={(saved) => {
            setDialog(null);
            notify(`Saved ${saved.name}.`);
          }}
        />
      )}
      {dialog === "register" && o && (
        <RegisterVehicleDialog
          token={token}
          role={user.role}
          initialOwner={o}
          onClose={() => setDialog(null)}
          onRegistered={(m) => {
            setDialog(null);
            notify(m);
          }}
        />
      )}
    </>
  );
}
