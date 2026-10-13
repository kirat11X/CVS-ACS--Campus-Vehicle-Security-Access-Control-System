import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import type { OwnerContext, PersonType, ResidenceType, Role, VehicleCategory } from "../api/types";
import { humanize, toLocalInput } from "../lib/format";
import { ErrorNote, Field, Modal, inputClass, primaryButton, secondaryButton } from "./Modal";
import { OwnerSearch } from "./OwnerSearch";

const ALL_CATEGORIES: VehicleCategory[] = ["STUDENT", "FACULTY", "STAFF", "RESIDENT", "VISITOR", "DELIVERY", "RIDE_HAILING", "UNKNOWN"];
// GUARD / SUPERVISOR may only register temporary entries with a validity window (enforced by the backend too).
const TEMPORARY_CATEGORIES: VehicleCategory[] = ["VISITOR", "DELIVERY"];
const PERSON_TYPES: PersonType[] = ["STUDENT", "FACULTY", "STAFF", "RESIDENT"];
const RESIDENCE_TYPES: ResidenceType[] = ["HOSTELLER", "DAY_SCHOLAR", "OFF_CAMPUS", "UNKNOWN"];

type OwnerMode = "none" | "search" | "create";

interface Props {
  token: string;
  role: Role;
  plate: string;
  onClose: () => void;
  onRegistered: (message: string) => void;
}

export function RegisterVehicleModal({ token, role, plate: initialPlate, onClose, onRegistered }: Props) {
  const isAdmin = role === "ADMIN";
  const categories = isAdmin ? ALL_CATEGORIES : TEMPORARY_CATEGORIES;
  const now = new Date();

  const [plate, setPlate] = useState(initialPlate);
  const [category, setCategory] = useState<VehicleCategory>("VISITOR");
  const [validFrom, setValidFrom] = useState(toLocalInput(now));
  const [validUntil, setValidUntil] = useState(toLocalInput(new Date(now.getTime() + 8 * 3600_000)));
  const [makeModel, setMakeModel] = useState("");
  const [color, setColor] = useState("");
  const [notes, setNotes] = useState("");

  const [ownerMode, setOwnerMode] = useState<OwnerMode>("none");
  const [owner, setOwner] = useState<OwnerContext | null>(null);
  const [newOwner, setNewOwner] = useState({
    identifier: "",
    full_name: "",
    phone: "",
    email: "",
    person_type: "STUDENT" as PersonType,
    residence_type: "UNKNOWN" as ResidenceType,
    residence: "",
    department: "",
  });

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const temporary = TEMPORARY_CATEGORIES.includes(category);
  const windowRequired = !isAdmin;
  const showWindow = windowRequired || temporary;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (windowRequired && !validUntil) {
      setError("A validity end time is required for this registration.");
      return;
    }
    setSubmitting(true);
    try {
      let ownerId = owner?.id ?? null;
      if (ownerMode === "create") {
        const created = await api.createOwner(token, {
          identifier: newOwner.identifier.trim(),
          full_name: newOwner.full_name.trim(),
          phone: newOwner.phone.trim() || null,
          email: newOwner.email.trim() || null,
          person_type: newOwner.person_type,
          residence_type: newOwner.residence_type,
          residence: newOwner.residence.trim() || null,
          department: newOwner.department.trim() || null,
        });
        // If the vehicle step fails, keep the created owner selected so a retry does not duplicate it.
        setOwner(created);
        setOwnerMode("search");
        ownerId = created.id;
      }
      await api.registerVehicle(token, {
        plate: plate.trim(),
        vehicle_category: category,
        owner_id: ownerMode === "none" ? null : ownerId,
        make_model: makeModel.trim() || null,
        color: color.trim() || null,
        valid_from: showWindow && validFrom ? new Date(validFrom).toISOString() : null,
        valid_until: showWindow && validUntil ? new Date(validUntil).toISOString() : null,
        notes: notes.trim() || null,
      });
      onRegistered(`Registered ${plate.trim().toUpperCase()} as ${humanize(category)}.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setError(err.message);
      else setError(err instanceof ApiError ? err.message : "Registration failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="Register vehicle"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="register-vehicle-form" className={primaryButton} disabled={submitting || !plate.trim()}>
            {submitting ? "Saving…" : "Register"}
          </button>
        </>
      }
    >
      <form id="register-vehicle-form" onSubmit={submit} className="space-y-4">
        <Field label="Plate">
          <input className={inputClass + " font-mono uppercase"} value={plate} maxLength={30} onChange={(e) => setPlate(e.target.value)} required />
        </Field>

        <Field
          label="Category"
          hint={isAdmin ? undefined : "Guards and supervisors can register visitor and delivery entries with a validity window. Other categories need an administrator."}
        >
          <select className={inputClass} value={category} onChange={(e) => setCategory(e.target.value as VehicleCategory)}>
            {categories.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </Field>

        {showWindow && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Valid from">
              <input type="datetime-local" className={inputClass} value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            </Field>
            <Field label={windowRequired ? "Valid until (required)" : "Valid until"}>
              <input
                type="datetime-local"
                className={inputClass}
                value={validUntil}
                required={windowRequired}
                onChange={(e) => setValidUntil(e.target.value)}
              />
            </Field>
          </div>
        )}

        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Owner</legend>
          <div className="mt-1 flex gap-2">
            {(["none", "search", ...(isAdmin ? (["create"] as const) : [])] as OwnerMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`${secondaryButton} px-2 py-1 text-xs ${ownerMode === mode ? "bg-slate-800 text-white hover:bg-slate-700" : ""}`}
                onClick={() => setOwnerMode(mode)}
              >
                {mode === "none" ? "No owner" : mode === "search" ? "Find owner" : "New owner"}
              </button>
            ))}
          </div>

          {ownerMode === "search" && (
            <div className="mt-2">
              <OwnerSearch token={token} selected={owner} onSelect={setOwner} />
            </div>
          )}

          {ownerMode === "create" && isAdmin && (
            <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Institutional ID">
                <input className={inputClass} required value={newOwner.identifier} maxLength={50}
                  onChange={(e) => setNewOwner({ ...newOwner, identifier: e.target.value })} />
              </Field>
              <Field label="Full name">
                <input className={inputClass} required value={newOwner.full_name} maxLength={100}
                  onChange={(e) => setNewOwner({ ...newOwner, full_name: e.target.value })} />
              </Field>
              <Field label="Person type">
                <select className={inputClass} value={newOwner.person_type}
                  onChange={(e) => setNewOwner({ ...newOwner, person_type: e.target.value as PersonType })}>
                  {PERSON_TYPES.map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
                </select>
              </Field>
              <Field label="Department">
                <input className={inputClass} value={newOwner.department} maxLength={100}
                  onChange={(e) => setNewOwner({ ...newOwner, department: e.target.value })} />
              </Field>
              <Field label="Residence type" hint="Residence is recorded on the person, not the vehicle.">
                <select className={inputClass} value={newOwner.residence_type}
                  onChange={(e) => setNewOwner({ ...newOwner, residence_type: e.target.value as ResidenceType })}>
                  {RESIDENCE_TYPES.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
                </select>
              </Field>
              <Field label="Residence (block / address)">
                <input className={inputClass} value={newOwner.residence} maxLength={100} placeholder="e.g. BH-4, Room 312"
                  onChange={(e) => setNewOwner({ ...newOwner, residence: e.target.value })} />
              </Field>
              <Field label="Phone">
                <input className={inputClass} value={newOwner.phone} maxLength={20}
                  onChange={(e) => setNewOwner({ ...newOwner, phone: e.target.value })} />
              </Field>
              <Field label="Email">
                <input type="email" className={inputClass} value={newOwner.email} maxLength={120}
                  onChange={(e) => setNewOwner({ ...newOwner, email: e.target.value })} />
              </Field>
            </div>
          )}
        </fieldset>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Make / model">
            <input className={inputClass} value={makeModel} maxLength={100} onChange={(e) => setMakeModel(e.target.value)} />
          </Field>
          <Field label="Colour">
            <input className={inputClass} value={color} maxLength={50} onChange={(e) => setColor(e.target.value)} />
          </Field>
        </div>
        <Field label="Notes" hint={temporary ? "e.g. visitor name, host, purpose or delivery platform" : undefined}>
          <textarea className={inputClass} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>

        <ErrorNote message={error} />
      </form>
    </Modal>
  );
}
