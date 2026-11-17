import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { REGISTRY_ROOTS, useInvalidate } from "../../api/queries";
import type { OwnerContext, PersonType, ResidenceType, Role, VehicleCategory } from "../../api/types";
import { humanize, toLocalInput } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Callout, ErrorNote } from "../ui/Feedback";
import { Field, Input, Select, Textarea } from "../ui/Form";
import { ALL_CATEGORIES, PERSON_TYPES, RESIDENCE_TYPES, TEMPORARY_CATEGORIES, blankToNull, getIdentifierGuide, validateIdentifier } from "./options";
import { OwnerSearch } from "./OwnerSearch";

/** Registers an unknown plate and links it to an owner, recording what was verified. */
export function LinkOwnerDialog({
  token,
  role,
  plate,
  initialPersonType = null,
  initialReference = "",
  onClose,
  onLinked,
}: {
  token: string;
  role: Role;
  plate: string;
  /** "Belongs to" chosen in the plate panel: Student / Faculty / Staff. */
  initialPersonType?: PersonType | null;
  /** SID / employee ID (searched and preselected on an exact match) or a department name. */
  initialReference?: string;
  onClose: () => void;
  onLinked: (message: string) => void;
}) {
  const isAdmin = role === "ADMIN";
  const categories = isAdmin ? ALL_CATEGORIES : TEMPORARY_CATEGORIES;
  const invalidate = useInvalidate();
  const [now] = useState(() => new Date());
  const reference = initialReference.trim();
  // "2410xxxx" / "EMP-104" is an ID; "CSE Department" is a department.
  const referenceIsId = /\d/.test(reference);

  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [owner, setOwner] = useState<OwnerContext | null>(null);
  const [newOwner, setNewOwner] = useState({
    person_type: (initialPersonType ?? "STUDENT") as PersonType,
    identifier: referenceIsId ? reference : "",
    full_name: "",
    residence_type: "UNKNOWN" as ResidenceType,
    residence: "",
    department: referenceIsId ? "" : reference,
  });
  // Administrators record the permanent category; guards and supervisors record a time-boxed link.
  const [category, setCategory] = useState<VehicleCategory>(isAdmin && initialPersonType ? initialPersonType : "VISITOR");
  const [validFrom, setValidFrom] = useState(toLocalInput(now));
  const [validUntil, setValidUntil] = useState(toLocalInput(new Date(now.getTime() + 8 * 3600_000)));
  const [evidence, setEvidence] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const windowRequired = !isAdmin;
  const showWindow = windowRequired || TEMPORARY_CATEGORIES.includes(category);
  const ownerReady = mode === "existing" ? owner !== null : newOwner.identifier.trim() !== "" && newOwner.full_name.trim() !== "";

  const guide = getIdentifierGuide(newOwner.person_type);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (mode === "new") {
      const idErr = validateIdentifier(newOwner.identifier, newOwner.person_type);
      if (idErr) {
        setError(idErr);
        return;
      }
    }
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
                residence: blankToNull(newOwner.residence),
                department: blankToNull(newOwner.department),
              }
            : null,
        vehicle_category: category,
        valid_from: showWindow && validFrom ? new Date(validFrom).toISOString() : null,
        valid_until: showWindow && validUntil ? new Date(validUntil).toISOString() : null,
        evidence_note: evidence.trim(),
      });
      void invalidate(...REGISTRY_ROOTS);
      const past = res.retroactive.movements + res.retroactive.sightings;
      onLinked(`Linked ${plate}. ${past} earlier record${past === 1 ? "" : "s"} now show this owner.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not link the vehicle.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title={`Link ${plate} to an owner`}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="link-owner-form" variant="primary" loading={submitting} disabled={!ownerReady || evidence.trim().length < 3}>
            Link vehicle
          </Button>
        </>
      }
    >
      <form id="link-owner-form" onSubmit={submit} className="space-y-4">
        <Callout>
          A link records what you checked; it is not proof of identity. Enter only the ID number, name and residence. Do not photograph or upload ID documents.
        </Callout>

        <div className="flex gap-2">
          {(["existing", "new"] as const).map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} className={`chip ${mode === m ? "chip-on" : "chip-off"}`} onClick={() => setMode(m)}>
              {m === "existing" ? "Existing owner" : "New owner"}
            </button>
          ))}
        </div>

        {mode === "existing" ? (
          <OwnerSearch token={token} selected={owner} onSelect={setOwner} initialQuery={referenceIsId ? reference : ""} personType={initialPersonType} />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Person type">
              <Select value={newOwner.person_type} onChange={(e) => setNewOwner({ ...newOwner, person_type: e.target.value as PersonType })}>
                {PERSON_TYPES.map((p) => (
                  <option key={p} value={p}>
                    {humanize(p)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={guide.label} hint={guide.hint}>
              <Input
                required
                maxLength={guide.maxLength}
                placeholder={guide.placeholder}
                value={newOwner.identifier}
                onChange={(e) => setNewOwner({ ...newOwner, identifier: e.target.value })}
              />
            </Field>
            <Field label="Full name">
              <Input required maxLength={100} value={newOwner.full_name} onChange={(e) => setNewOwner({ ...newOwner, full_name: e.target.value })} />
            </Field>
            <Field label="Department (optional)">
              <Input maxLength={100} value={newOwner.department} onChange={(e) => setNewOwner({ ...newOwner, department: e.target.value })} />
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
              <Input maxLength={100} placeholder="e.g. BH-2, Room 104" value={newOwner.residence} onChange={(e) => setNewOwner({ ...newOwner, residence: e.target.value })} />
            </Field>
          </div>
        )}

        <Field label="Vehicle category" hint={isAdmin ? undefined : "Guards and supervisors can create visitor or delivery links with an end time. Permanent links need an administrator."}>
          <Select value={category} onChange={(e) => setCategory(e.target.value as VehicleCategory)}>
            {categories.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </Select>
        </Field>

        {showWindow && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Valid from">
              <Input type="datetime-local" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
            </Field>
            <Field label={windowRequired ? "Expires (required)" : "Expires"}>
              <Input type="datetime-local" required={windowRequired} value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
            </Field>
          </div>
        )}

        <Field label="What did you verify? (required)">
          <Textarea rows={2} maxLength={1000} placeholder="e.g. Student ID card shown by driver; name matches" value={evidence} onChange={(e) => setEvidence(e.target.value)} required />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
