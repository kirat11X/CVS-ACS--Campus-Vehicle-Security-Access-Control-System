import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import type { OwnerContext, PersonType, ResidenceType, Role, VehicleCategory } from "../../api/types";
import { humanize, toLocalInput } from "../../lib/format";
import { ErrorNote, Field, Modal, inputClass, primaryButton, secondaryButton } from "../Modal";
import { OwnerSearch } from "../OwnerSearch";

const ALL_CATEGORIES: VehicleCategory[] = ["STUDENT", "FACULTY", "STAFF", "RESIDENT", "VISITOR", "DELIVERY", "RIDE_HAILING", "UNKNOWN"];
const TEMPORARY_CATEGORIES: VehicleCategory[] = ["VISITOR", "DELIVERY"];
const PERSON_TYPES: PersonType[] = ["STUDENT", "FACULTY", "STAFF", "RESIDENT"];
const RESIDENCE_TYPES: ResidenceType[] = ["HOSTELLER", "DAY_SCHOLAR", "OFF_CAMPUS", "UNKNOWN"];

interface Props {
  token: string;
  role: Role;
  plate: string;
  onClose: () => void;
  onLinked: (message: string) => void;
}

/** Registers an unknown plate and links it to an owner, recording what was verified. */
export function LinkOwnerModal({ token, role, plate, onClose, onLinked }: Props) {
  const isAdmin = role === "ADMIN";
  const categories = isAdmin ? ALL_CATEGORIES : TEMPORARY_CATEGORIES;
  const now = new Date();

  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [owner, setOwner] = useState<OwnerContext | null>(null);
  const [newOwner, setNewOwner] = useState({
    person_type: "STUDENT" as PersonType,
    identifier: "",
    full_name: "",
    residence_type: "UNKNOWN" as ResidenceType,
    residence: "",
    department: "",
  });
  const [category, setCategory] = useState<VehicleCategory>("VISITOR");
  const [validFrom, setValidFrom] = useState(toLocalInput(now));
  const [validUntil, setValidUntil] = useState(toLocalInput(new Date(now.getTime() + 8 * 3600_000)));
  const [evidence, setEvidence] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const windowRequired = !isAdmin;
  const showWindow = windowRequired || TEMPORARY_CATEGORIES.includes(category);
  const ownerReady = mode === "existing" ? owner !== null : newOwner.identifier.trim() !== "" && newOwner.full_name.trim() !== "";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.linkVehicle(token, plate, {
        owner_id: mode === "existing" ? owner?.id : null,
        new_owner:
          mode === "new"
            ? {
                person_type: newOwner.person_type,
                identifier: newOwner.identifier.trim(),
                full_name: newOwner.full_name.trim(),
                residence_type: newOwner.residence_type,
                residence: newOwner.residence.trim() || null,
                department: newOwner.department.trim() || null,
              }
            : null,
        vehicle_category: category,
        valid_from: showWindow && validFrom ? new Date(validFrom).toISOString() : null,
        valid_until: showWindow && validUntil ? new Date(validUntil).toISOString() : null,
        evidence_note: evidence.trim(),
      });
      const past = res.retroactive.movements + res.retroactive.sightings;
      onLinked(`Linked ${plate}. ${past} earlier record${past === 1 ? "" : "s"} now show this owner.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not link the vehicle.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={`Link ${plate} to an owner`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="link-owner-form"
            className={primaryButton}
            disabled={submitting || !ownerReady || evidence.trim().length < 3}
          >
            {submitting ? "Saving…" : "Link vehicle"}
          </button>
        </>
      }
    >
      <form id="link-owner-form" onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-600">
          A link records what you checked; it is not proof of identity. Enter only the ID number, name and residence. Do not photograph or upload ID
          documents.
        </p>

        <div className="flex gap-2">
          {(["existing", "new"] as const).map((m) => (
            <button
              key={m}
              type="button"
              className={`${secondaryButton} px-2 py-1 text-xs ${mode === m ? "bg-slate-800 text-white hover:bg-slate-700" : ""}`}
              onClick={() => setMode(m)}
            >
              {m === "existing" ? "Existing owner" : "New owner"}
            </button>
          ))}
        </div>

        {mode === "existing" ? (
          <OwnerSearch token={token} selected={owner} onSelect={setOwner} />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Person type">
              <select className={inputClass} value={newOwner.person_type} onChange={(e) => setNewOwner({ ...newOwner, person_type: e.target.value as PersonType })}>
                {PERSON_TYPES.map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
              </select>
            </Field>
            <Field label="ID number (SID / employee ID)">
              <input className={inputClass} required maxLength={50} value={newOwner.identifier} onChange={(e) => setNewOwner({ ...newOwner, identifier: e.target.value })} />
            </Field>
            <Field label="Full name">
              <input className={inputClass} required maxLength={100} value={newOwner.full_name} onChange={(e) => setNewOwner({ ...newOwner, full_name: e.target.value })} />
            </Field>
            <Field label="Department (optional)">
              <input className={inputClass} maxLength={100} value={newOwner.department} onChange={(e) => setNewOwner({ ...newOwner, department: e.target.value })} />
            </Field>
            <Field label="Residence type" hint="Residence is recorded on the person, not the vehicle.">
              <select className={inputClass} value={newOwner.residence_type} onChange={(e) => setNewOwner({ ...newOwner, residence_type: e.target.value as ResidenceType })}>
                {RESIDENCE_TYPES.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
              </select>
            </Field>
            <Field label="Residence (block / address)">
              <input className={inputClass} maxLength={100} placeholder="e.g. BH-2, Room 104" value={newOwner.residence} onChange={(e) => setNewOwner({ ...newOwner, residence: e.target.value })} />
            </Field>
          </div>
        )}

        <Field
          label="Vehicle category"
          hint={isAdmin ? undefined : "Guards and supervisors can create visitor or delivery links with an end time. Permanent links need an administrator."}
        >
          <select className={inputClass} value={category} onChange={(e) => setCategory(e.target.value as VehicleCategory)}>
            {categories.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
          </select>
        </Field>

        {showWindow && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Valid from">
              <input type="datetime-local" className={inputClass} value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            </Field>
            <Field label={windowRequired ? "Expires (required)" : "Expires"}>
              <input type="datetime-local" className={inputClass} required={windowRequired} value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
            </Field>
          </div>
        )}

        <Field label="What did you verify? (required)">
          <textarea
            className={inputClass}
            rows={2}
            maxLength={1000}
            placeholder="e.g. Student ID card shown by driver; name matches"
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            required
          />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Modal>
  );
}
