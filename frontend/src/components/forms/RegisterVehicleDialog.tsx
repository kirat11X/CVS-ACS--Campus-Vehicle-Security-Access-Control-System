import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { REGISTRY_ROOTS, useInvalidate } from "../../api/queries";
import type { OwnerContext, PersonType, ResidenceType, Role, VehicleCategory } from "../../api/types";
import { humanize, toLocalInput } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { ErrorNote } from "../ui/Feedback";
import { Field, Input, Select, Textarea } from "../ui/Form";
import { ALL_CATEGORIES, PERSON_TYPES, RESIDENCE_TYPES, TEMPORARY_CATEGORIES, blankToNull, getIdentifierGuide, validateIdentifier } from "./options";
import { OwnerSearch } from "./OwnerSearch";

type OwnerMode = "none" | "search" | "create";

interface Props {
  token: string;
  role: Role;
  plate?: string;
  initialOwner?: OwnerContext | null;
  onClose: () => void;
  onRegistered: (message: string, plate: string) => void;
}

export function RegisterVehicleDialog({ token, role, plate: initialPlate = "", initialOwner = null, onClose, onRegistered }: Props) {
  const isAdmin = role === "ADMIN";
  const categories = isAdmin ? ALL_CATEGORIES : TEMPORARY_CATEGORIES;
  const invalidate = useInvalidate();
  const [now] = useState(() => new Date());

  const [plate, setPlate] = useState(initialPlate);
  const [category, setCategory] = useState<VehicleCategory>(initialOwner && isAdmin ? "STUDENT" : "VISITOR");
  const [validFrom, setValidFrom] = useState(toLocalInput(now));
  const [validUntil, setValidUntil] = useState(toLocalInput(new Date(now.getTime() + 8 * 3600_000)));
  const [makeModel, setMakeModel] = useState("");
  const [color, setColor] = useState("");
  const [notes, setNotes] = useState("");

  const [ownerMode, setOwnerMode] = useState<OwnerMode>(initialOwner ? "search" : "none");
  const [owner, setOwner] = useState<OwnerContext | null>(initialOwner);
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

  const guide = getIdentifierGuide(newOwner.person_type);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (windowRequired && !validUntil) {
      setError("A validity end time is required for this registration.");
      return;
    }
    if (ownerMode === "search" && !owner) {
      setError("Choose an owner, or select “No owner”.");
      return;
    }
    if (ownerMode === "create") {
      const idErr = validateIdentifier(newOwner.identifier, newOwner.person_type);
      if (idErr) {
        setError(idErr);
        return;
      }
    }
    setSubmitting(true);
    try {
      let ownerId = owner?.id ?? null;
      if (ownerMode === "create") {
        const created = await api.createOwner(token, {
          identifier: newOwner.identifier.trim(),
          full_name: newOwner.full_name.trim(),
          phone: blankToNull(newOwner.phone),
          email: blankToNull(newOwner.email),
          person_type: newOwner.person_type,
          residence_type: newOwner.residence_type,
          residence: blankToNull(newOwner.residence),
          department: blankToNull(newOwner.department),
        });
        // If the vehicle step fails, keep the created owner selected so a retry does not duplicate it.
        setOwner(created);
        setOwnerMode("search");
        ownerId = created.id;
      }
      const normalized = plate.trim().toUpperCase();
      await api.registerVehicle(token, {
        plate: plate.trim(),
        vehicle_category: category,
        owner_id: ownerMode === "none" ? null : ownerId,
        make_model: blankToNull(makeModel),
        color: blankToNull(color),
        valid_from: showWindow && validFrom ? new Date(validFrom).toISOString() : null,
        valid_until: showWindow && validUntil ? new Date(validUntil).toISOString() : null,
        notes: blankToNull(notes),
      });
      void invalidate(...REGISTRY_ROOTS);
      onRegistered(`Registered ${normalized} as ${humanize(category)}.`, normalized);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const modes: OwnerMode[] = ["none", "search", ...(isAdmin ? (["create"] as const) : [])];

  return (
    <Dialog
      title="Register vehicle"
      description={isAdmin ? undefined : "Guards and supervisors can register visitor and delivery entries with a validity window."}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="register-vehicle-form" variant="primary" loading={submitting} disabled={!plate.trim()}>
            Register
          </Button>
        </>
      }
    >
      <form id="register-vehicle-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Plate">
            <Input className="plate" value={plate} maxLength={30} onChange={(e) => setPlate(e.target.value)} required autoCapitalize="characters" autoComplete="off" />
          </Field>
          <Field label="Category" hint={isAdmin ? undefined : "Other categories need an administrator."}>
            <Select value={category} onChange={(e) => setCategory(e.target.value as VehicleCategory)}>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {humanize(c)}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {showWindow && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Valid from">
              <Input type="datetime-local" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            </Field>
            <Field label={windowRequired ? "Valid until (required)" : "Valid until"}>
              <Input type="datetime-local" value={validUntil} required={windowRequired} onChange={(e) => setValidUntil(e.target.value)} />
            </Field>
          </div>
        )}

        <fieldset className="space-y-2">
          <legend className="label">Owner</legend>
          <div className="flex flex-wrap gap-2">
            {modes.map((mode) => (
              <button key={mode} type="button" aria-pressed={ownerMode === mode} className={`chip ${ownerMode === mode ? "chip-on" : "chip-off"}`} onClick={() => setOwnerMode(mode)}>
                {mode === "none" ? "No owner" : mode === "search" ? "Find owner" : "New owner"}
              </button>
            ))}
          </div>

          {ownerMode === "search" && <OwnerSearch token={token} selected={owner} onSelect={setOwner} />}

          {ownerMode === "create" && isAdmin && (
            <div className="grid grid-cols-1 gap-3 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200 dark:bg-slate-800/40 dark:ring-slate-700 sm:grid-cols-2">
              <Field label={guide.label} hint={guide.hint}>
                <Input
                  required
                  value={newOwner.identifier}
                  maxLength={guide.maxLength}
                  placeholder={guide.placeholder}
                  onChange={(e) => setNewOwner({ ...newOwner, identifier: e.target.value })}
                />
              </Field>
              <Field label="Full name">
                <Input required value={newOwner.full_name} maxLength={100} onChange={(e) => setNewOwner({ ...newOwner, full_name: e.target.value })} />
              </Field>
              <Field label="Person type">
                <Select value={newOwner.person_type} onChange={(e) => setNewOwner({ ...newOwner, person_type: e.target.value as PersonType })}>
                  {PERSON_TYPES.map((p) => (
                    <option key={p} value={p}>
                      {humanize(p)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Department">
                <Input value={newOwner.department} maxLength={100} onChange={(e) => setNewOwner({ ...newOwner, department: e.target.value })} />
              </Field>
              <Field label="Residence type" hint="Residence is recorded on the person, not the vehicle.">
                <Select value={newOwner.residence_type} onChange={(e) => setNewOwner({ ...newOwner, residence_type: e.target.value as ResidenceType })}>
                  {RESIDENCE_TYPES.map((r) => (
                    <option key={r} value={r}>
                      {humanize(r)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Residence (block / address)">
                <Input value={newOwner.residence} maxLength={100} placeholder="e.g. BH-4, Room 312" onChange={(e) => setNewOwner({ ...newOwner, residence: e.target.value })} />
              </Field>
              <Field label="Phone">
                <Input type="tel" value={newOwner.phone} maxLength={20} onChange={(e) => setNewOwner({ ...newOwner, phone: e.target.value })} />
              </Field>
              <Field label="Email">
                <Input type="email" value={newOwner.email} maxLength={120} onChange={(e) => setNewOwner({ ...newOwner, email: e.target.value })} />
              </Field>
            </div>
          )}
        </fieldset>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Make / model">
            <Input value={makeModel} maxLength={100} onChange={(e) => setMakeModel(e.target.value)} />
          </Field>
          <Field label="Colour">
            <Input value={color} maxLength={50} onChange={(e) => setColor(e.target.value)} />
          </Field>
        </div>
        <Field label="Notes" hint={temporary ? "e.g. visitor name, host, purpose or delivery platform" : undefined}>
          <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>

        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
