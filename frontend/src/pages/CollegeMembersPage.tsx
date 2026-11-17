import {
  Building2,
  Car,
  CheckCircle2,
  Database,
  GraduationCap,
  Mail,
  Phone,
  Plus,
  Shield,
  Trash2,
  UserCheck,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import { useOwners, useVehicles } from "../api/queries";
import type { OwnerContext, PersonType } from "../api/types";
import { useSession } from "../auth/AuthContext";
import { OwnerFormDialog } from "../components/forms/OwnerFormDialog";
import { RegisterVehicleDialog } from "../components/forms/RegisterVehicleDialog";
import { Button } from "../components/ui/Button";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState, SkeletonRows } from "../components/ui/Feedback";
import { SearchInput, Select } from "../components/ui/Form";
import { FilterChips, PageHeader, Pagination, StatTile } from "../components/ui/Layout";
import { useToast } from "../components/ui/Toast";
import { cx } from "../lib/cx";
import { initials } from "../lib/format";
import { useDebounced } from "../lib/hooks";

type SectionTab = "ALL" | "FACULTY" | "STAFF" | "STUDENT" | "RESIDENT";

const TABS: { value: SectionTab; label: string; count?: number }[] = [
  { value: "ALL", label: "All Members" },
  { value: "FACULTY", label: "Faculty ID (F...)" },
  { value: "STAFF", label: "Administration ID (STF-...)" },
  { value: "STUDENT", label: "Student ID (2410xxxx)" },
  { value: "RESIDENT", label: "Residence ID (R...)" },
];

const DEPARTMENTS = [
  "All Departments",
  "Computer Science & Engineering",
  "Electronics & Communication Engineering",
  "Electrical Engineering",
  "Mechanical Engineering",
  "Civil Engineering",
  "Aerospace Engineering",
  "Metallurgical & Materials Engineering",
  "Production & Industrial Engineering",
  "Estate & Maintenance Office",
  "Dean Academics & Student Welfare",
  "Chief Security Office",
  "Registrar Secretariat",
  "Campus Residential Complex",
];

const PAGE_SIZE = 50;

export function CollegeMembersPage() {
  const { user, token } = useSession();
  const isAdmin = user.role === "ADMIN";
  const notify = useToast();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [deptFilter, setDeptFilter] = useState(params.get("dept") ?? "All Departments");
  const [activeTab, setActiveTab] = useState<SectionTab>((params.get("tab") as SectionTab) || "ALL");
  const [creatingOwner, setCreatingOwner] = useState(false);
  const [registeringVehicleForOwner, setRegisteringVehicleForOwner] = useState<OwnerContext | null>(null);
  const [deletingMember, setDeletingMember] = useState<OwnerContext | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDatasetInfo, setShowDatasetInfo] = useState(false);

  const debouncedQ = useDebounced(q.trim(), 250);
  const skip = Math.max(0, Number(params.get("skip")) || 0);

  // Map activeTab to PersonType query param
  const personTypeParam: PersonType | undefined =
    activeTab === "ALL" ? undefined : (activeTab as PersonType);

  // Fetch all members with large limit so live directory feels instant
  const ownersQuery = useOwners({
    q: debouncedQ.length >= 1 ? debouncedQ : undefined,
    person_type: personTypeParam,
    skip,
    limit: PAGE_SIZE,
  });

  // Query global counts for overview stat tiles
  const allMembersQuery = useOwners({ limit: 1000 });
  const vehiclesQuery = useVehicles({ limit: 1000 });

  const allMembers = allMembersQuery.data ?? [];
  const rows = ownersQuery.data ?? [];

  // Metrics computation
  const stats = useMemo(() => {
    let students = 0;
    let faculty = 0;
    let staff = 0;
    let residents = 0;
    for (const m of allMembers) {
      if (m.person_type === "STUDENT") students++;
      else if (m.person_type === "FACULTY") faculty++;
      else if (m.person_type === "STAFF") staff++;
      else if (m.person_type === "RESIDENT") residents++;
    }
    return {
      total: allMembers.length,
      students,
      faculty,
      staff,
      residents,
      vehicles: vehiclesQuery.data?.length ?? 0,
    };
  }, [allMembers, vehiclesQuery.data]);

  // Client-side department filter if chosen
  const filteredRows = useMemo(() => {
    if (deptFilter === "All Departments") return rows;
    return rows.filter((r) => (r.department || "").toLowerCase().includes(deptFilter.toLowerCase()));
  }, [rows, deptFilter]);

  const handleTabChange = (tab: SectionTab) => {
    setActiveTab(tab);
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (tab === "ALL") next.delete("tab");
        else next.set("tab", tab);
        next.delete("skip");
        return next;
      },
      { replace: true }
    );
  };

  const confirmDelete = async () => {
    if (!deletingMember) return;
    setIsDeleting(true);
    try {
      await api.deleteOwner(token, deletingMember.id);
      notify(`Member '${deletingMember.name}' (${deletingMember.institutional_id}) deleted from PostgreSQL.`);
      setDeletingMember(null);
      ownersQuery.refetch();
      allMembersQuery.refetch();
      vehiclesQuery.refetch();
    } catch (e: any) {
      notify(e.message || "Failed to delete member.", "info");
    } finally {
      setIsDeleting(false);
    }
  };

  const getRoleBadgeStyle = (pType: string | null) => {
    switch (pType) {
      case "FACULTY":
        return "bg-purple-50 text-purple-700 ring-purple-600/20 dark:bg-purple-500/10 dark:text-purple-300 dark:ring-purple-500/30";
      case "STAFF":
        return "bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30";
      case "STUDENT":
        return "bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/30";
      case "RESIDENT":
        return "bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30";
      default:
        return "bg-slate-50 text-slate-700 ring-slate-600/20 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700";
    }
  };

  const getIdBadgePrefix = (pType: string | null) => {
    switch (pType) {
      case "FACULTY":
        return "FID";
      case "STAFF":
        return "ADMIN";
      case "STUDENT":
        return "SID";
      case "RESIDENT":
        return "RES";
      default:
        return "ID";
    }
  };

  return (
    <>
      <PageHeader
        title="College Members Directory"
        description="Official institutional registry of all campus members: Faculty, Administration Staff, Students, and Campus Residents with linked vehicles and access privileges."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={<Database className="h-4 w-4" />}
              onClick={() => setShowDatasetInfo(true)}
              title="Inspect live PostgreSQL storage and purge options"
            >
              PostgreSQL Dataset
            </Button>
            {isAdmin && (
              <Button
                variant="primary"
                icon={<Plus className="h-4 w-4" />}
                onClick={() => setCreatingOwner(true)}
              >
                Add Member
              </Button>
            )}
          </div>
        }
      />

      {/* Overview Stat Tiles */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile
          label="All Members"
          value={stats.total}
          sub="Registered on campus"
          icon={<Users className="h-5 w-5" />}
        />
        <StatTile
          label="Faculty Members"
          value={stats.faculty}
          sub="Professors & HODs"
          icon={<GraduationCap className="h-5 w-5" />}
        />
        <StatTile
          label="Administration & Staff"
          value={stats.staff}
          sub="Offices & Security"
          icon={<Shield className="h-5 w-5" />}
        />
        <StatTile
          label="Student Body"
          value={stats.students}
          sub="Hostellers & Day Scholars"
          icon={<UserCheck className="h-5 w-5" />}
        />
        <StatTile
          label="Campus Residents"
          value={stats.residents}
          sub="Enclave quarters"
          icon={<Building2 className="h-5 w-5" />}
        />
      </div>

      {/* Section Tabs */}
      <div className="mb-4">
        <FilterChips
          label="Member Categories"
          options={TABS}
          value={activeTab}
          onChange={handleTabChange}
        />
      </div>

      {/* Search and Filters Bar */}
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          label="Search members"
          placeholder="Search by name, ID (e.g. 2410..., F100..., R10...), department, or vehicle plate"
          value={q}
          onChange={(v) => {
            setQ(v);
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                if (v.trim()) next.set("q", v.trim());
                else next.delete("q");
                next.delete("skip");
                return next;
              },
              { replace: true }
            );
          }}
          className="flex-1"
        />

        <div className="sm:w-64">
          <Select
            value={deptFilter}
            onChange={(e) => {
              setDeptFilter(e.target.value);
              setParams(
                (prev) => {
                  const next = new URLSearchParams(prev);
                  if (e.target.value !== "All Departments") next.set("dept", e.target.value);
                  else next.delete("dept");
                  return next;
                },
                { replace: true }
              );
            }}
            aria-label="Department Filter"
          >
            {DEPARTMENTS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {/* Members Directory Content */}
      <div className="card divide-y divide-slate-100 overflow-hidden dark:divide-slate-800">
        {ownersQuery.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={8} />
          </div>
        ) : filteredRows.length === 0 ? (
          <EmptyState
            icon={<Users className="h-8 w-8 text-slate-400" />}
            title="No college members found"
            description={
              q
                ? `No members match search query "${q}". Check spelling or search by institutional ID.`
                : "No members found in this category."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm dark:divide-slate-800">
              <thead className="bg-slate-50/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-3">Member Details</th>
                  <th className="px-4 py-3">Institutional ID</th>
                  <th className="px-4 py-3">Department & Office</th>
                  <th className="px-4 py-3">Campus Residence / Hostel</th>
                  <th className="px-4 py-3">Contact</th>
                  <th className="px-4 py-3">Linked Vehicles</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filteredRows.map((m) => {
                  const pType = m.person_type || "MEMBER";
                  const badgeCls = getRoleBadgeStyle(pType);
                  const idPrefix = getIdBadgePrefix(pType);
                  const plates = m.vehicle_plates || [];

                  return (
                    <tr
                      key={m.id}
                      className="hover:bg-slate-50/70 transition-colors dark:hover:bg-slate-800/40"
                    >
                      {/* Member Name + Avatar */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-3">
                          <span
                            className={cx(
                              "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1",
                              badgeCls
                            )}
                          >
                            {initials(m.name)}
                          </span>
                          <div className="min-w-0">
                            <Link
                              to={`/owners/${m.id}`}
                              className="font-medium text-slate-900 hover:text-sky-600 dark:text-white dark:hover:text-sky-400"
                            >
                              {m.name}
                            </Link>
                            <div className="mt-0.5 flex items-center gap-1.5">
                              <span
                                className={cx(
                                  "inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
                                  badgeCls
                                )}
                              >
                                {pType}
                              </span>
                              {m.status === "ACTIVE" && (
                                <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400">
                                  <CheckCircle2 className="h-2.5 w-2.5" /> Active
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Institutional ID Badge */}
                      <td className="px-4 py-3.5">
                        <div className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-1 font-mono text-xs font-semibold text-slate-800 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                          <span className="text-[10px] font-medium text-slate-400 dark:text-slate-500">
                            {idPrefix}
                          </span>
                          <span className="text-slate-900 dark:text-white">
                            {m.institutional_id}
                          </span>
                        </div>
                      </td>

                      {/* Department / Branch */}
                      <td className="px-4 py-3.5">
                        <span className="text-xs text-slate-700 dark:text-slate-300">
                          {m.department || "General"}
                        </span>
                      </td>

                      {/* Residence / Hostel & Room */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
                          <Building2 className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                          <span className="truncate max-w-[180px]" title={m.residence || "—"}>
                            {m.residence || "—"}
                          </span>
                        </div>
                      </td>

                      {/* Contact */}
                      <td className="px-4 py-3.5">
                        <div className="space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                          {m.email && (
                            <div className="flex items-center gap-1 truncate max-w-[170px]" title={m.email}>
                              <Mail className="h-3 w-3 shrink-0 text-slate-400" />
                              <span className="truncate">{m.email}</span>
                            </div>
                          )}
                          {m.phone && (
                            <div className="flex items-center gap-1">
                              <Phone className="h-3 w-3 shrink-0 text-slate-400" />
                              <span>{m.phone}</span>
                            </div>
                          )}
                        </div>
                      </td>

                      {/* Linked Vehicles */}
                      <td className="px-4 py-3.5">
                        {plates.length === 0 ? (
                          <span className="text-xs text-slate-400 italic">No vehicle linked</span>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {plates.map((plate) => (
                              <Link
                                key={plate}
                                to={`/vehicles/${plate}`}
                                className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] font-medium text-slate-700 ring-1 ring-slate-200 hover:bg-sky-50 hover:text-sky-700 hover:ring-sky-300 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700 dark:hover:bg-sky-950 dark:hover:text-sky-300"
                              >
                                <Car className="h-3 w-3 text-slate-400" />
                                {plate}
                              </Link>
                            ))}
                          </div>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setRegisteringVehicleForOwner(m)}
                            title="Register vehicle for this member"
                          >
                            + Vehicle
                          </Button>
                          <Link to={`/owners/${m.id}`}>
                            <Button size="sm">Profile</Button>
                          </Link>
                          {isAdmin && (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-400 dark:hover:bg-rose-950/40"
                              onClick={() => setDeletingMember(m)}
                              title="Delete member from PostgreSQL"
                              icon={<Trash2 className="h-3.5 w-3.5" />}
                            />
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          skip={skip}
          limit={PAGE_SIZE}
          count={filteredRows.length}
          onChange={(newSkip) => {
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                next.set("skip", String(newSkip));
                return next;
              },
              { replace: true }
            );
          }}
        />
      </div>

      {/* Create Member Dialog */}
      {creatingOwner && (
        <OwnerFormDialog
          token={token}
          owner={null}
          onClose={() => setCreatingOwner(false)}
          onSaved={() => {
            setCreatingOwner(false);
            ownersQuery.refetch();
            allMembersQuery.refetch();
          }}
        />
      )}

      {/* Register Vehicle Dialog */}
      {registeringVehicleForOwner && (
        <RegisterVehicleDialog
          token={token}
          role={user.role}
          initialOwner={registeringVehicleForOwner}
          onClose={() => setRegisteringVehicleForOwner(null)}
          onRegistered={() => {
            setRegisteringVehicleForOwner(null);
            ownersQuery.refetch();
            vehiclesQuery.refetch();
          }}
        />
      )}

      {/* Delete Member Confirmation Dialog */}
      {deletingMember && (
        <Dialog
          title="Delete Member from PostgreSQL"
          description="Are you sure you want to delete this member from the institutional database?"
          onClose={() => setDeletingMember(null)}
          footer={
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setDeletingMember(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                className="bg-rose-600 hover:bg-rose-700 text-white focus-visible:ring-rose-500"
                loading={isDeleting}
                onClick={confirmDelete}
              >
                Delete from PostgreSQL
              </Button>
            </div>
          }
        >
          <div className="space-y-3 text-sm">
            <p className="text-slate-700 dark:text-slate-300">
              You are about to delete <strong>{deletingMember.name}</strong> (Institutional ID:{" "}
              <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-semibold dark:bg-slate-800">
                {deletingMember.institutional_id}
              </code>
              ).
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              This will remove the member record from the PostgreSQL <code>vehicle_owners</code> table, de-link any associated vehicles, and purge related links.
            </p>
          </div>
        </Dialog>
      )}

      {/* PostgreSQL Dataset Info & Management Modal */}
      {showDatasetInfo && (
        <Dialog
          title="PostgreSQL Dataset Architecture"
          description="Live database-backed storage and purge management for CVS-ACS."
          onClose={() => setShowDatasetInfo(false)}
          footer={
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setShowDatasetInfo(false)}>
                Close
              </Button>
            </div>
          }
        >
          <div className="space-y-4 text-sm">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3.5 dark:border-slate-800 dark:bg-slate-900/50">
              <h4 className="font-semibold text-slate-900 dark:text-white flex items-center gap-2">
                <Database className="h-4 w-4 text-sky-500" /> PostgreSQL Live Table Counts
              </h4>
              <ul className="mt-2 space-y-1 text-xs text-slate-600 dark:text-slate-400">
                <li>• <strong>Students:</strong> {stats.students} records in <code>vehicle_owners</code></li>
                <li>• <strong>Faculty:</strong> {stats.faculty} records in <code>vehicle_owners</code></li>
                <li>• <strong>Residents:</strong> {stats.residents} records in <code>vehicle_owners</code></li>
                <li>• <strong>Staff:</strong> {stats.staff} records in <code>vehicle_owners</code></li>
                <li>• <strong>Vehicles:</strong> {stats.vehicles} records in <code>vehicles</code></li>
                <li>• <strong>Invoices & Orders:</strong> 1,000 multi-vendor orders with QR receipts</li>
              </ul>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Every member, vehicle, and invoice is stored in PostgreSQL and can be deleted individually using the red delete icon, or in bulk via the server CLI:
            </p>
            <div className="rounded bg-slate-900 p-2.5 font-mono text-xs text-emerald-400">
              python scripts/manage_dataset.py --purge-all<br />
              python scripts/manage_dataset.py --purge-invoices<br />
              python scripts/manage_dataset.py --purge-members<br />
              python scripts/manage_dataset.py --status
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}
