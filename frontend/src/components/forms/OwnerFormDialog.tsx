import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { REGISTRY_ROOTS, useInvalidate } from "../../api/queries";
import type { OwnerContext, OwnerUpdate, PersonType, ResidenceType } from "../../api/types";
import { humanize } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { ErrorNote } from "../ui/Feedback";
import { Field, Input, Select } from "../ui/Form";
import { PERSON_TYPES, RESIDENCE_TYPES, blankToNull, getIdentifierGuide, validateIdentifier } from "./options";

/** Create (owner = null) or edit an owner. ADMIN only; the institutional ID cannot change. */
export function OwnerFormDialog({
  token,
  owner,
  onClose,
  onSaved,
}: {
  token: string;
  owner: OwnerContext | null;
  onClose: () => void;
  onSaved: (owner: OwnerContext) => void;
}) {
  const invalidate = useInvalidate();
  const [form, setForm] = useState({
    identifier: owner?.institutional_id ?? "",
    full_name: owner?.name ?? "",
    person_type: (owner?.person_type as PersonType) ?? "STUDENT",
    residence_type: (owner?.residence_type as ResidenceType) ?? "UNKNOWN",
    residence: owner?.residence ?? "",
    department: owner?.department ?? "",
    phone: owner?.phone ?? "",
    email: owner?.email ?? "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));

  const guide = getIdentifierGuide(form.person_type);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!owner) {
      const idErr = validateIdentifier(form.identifier, form.person_type);
      if (idErr) {
        setError(idErr);
        return;
      }
    }
    setSubmitting(true);
    setError(null);
    try {
      let saved: OwnerContext;
      if (owner) {
        const body: OwnerUpdate = {};
        if (form.full_name.trim() !== owner.name) body.full_name = form.full_name.trim();
        if (form.person_type !== owner.person_type) body.person_type = form.person_type;
        if (form.residence_type !== owner.residence_type) body.residence_type = form.residence_type;
        for (const key of ["residence", "department", "phone", "email"] as const) {
          const next = blankToNull(form[key]);
          if (next !== (owner[key] ?? null)) body[key] = next;
        }
        saved = Object.keys(body).length ? (await api.updateOwner(token, owner.id, body)).owner : owner;
      } else {
        saved = await api.createOwner(token, {
          identifier: form.identifier.trim(),
          full_name: form.full_name.trim(),
          person_type: form.person_type,
          residence_type: form.residence_type,
          residence: blankToNull(form.residence),
          department: blankToNull(form.department),
          phone: blankToNull(form.phone),
          email: blankToNull(form.email),
        });
      }
      void invalidate(...REGISTRY_ROOTS);
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the owner.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title={owner ? `Edit ${owner.name}` : "New owner"}
      description="Residence belongs to the person: a change here applies to all of their vehicles."
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="owner-form" variant="primary" loading={submitting} disabled={!form.full_name.trim() || !form.identifier.trim()}>
            {owner ? "Save changes" : "Create owner"}
          </Button>
        </>
      }
    >
      <form id="owner-form" onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label={guide.label} hint={owner ? "Cannot be changed." : guide.hint}>
          <Input
            value={form.identifier}
            maxLength={guide.maxLength}
            placeholder={guide.placeholder}
            required
            disabled={!!owner}
            onChange={(e) => set({ identifier: e.target.value })}
          />
        </Field>
        <Field label="Full name">
          <Input value={form.full_name} maxLength={100} required onChange={(e) => set({ full_name: e.target.value })} />
        </Field>
        <Field label="Person type">
          <Select value={form.person_type} onChange={(e) => set({ person_type: e.target.value as PersonType })}>
            {PERSON_TYPES.map((p) => (
              <option key={p} value={p}>
                {humanize(p)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Department">
          <Input value={form.department} maxLength={100} onChange={(e) => set({ department: e.target.value })} />
        </Field>
        <Field label="Residence type">
          <Select value={form.residence_type} onChange={(e) => set({ residence_type: e.target.value as ResidenceType })}>
            {RESIDENCE_TYPES.map((r) => (
              <option key={r} value={r}>
                {humanize(r)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Residence (block / address)">
          <Input value={form.residence} maxLength={100} placeholder="e.g. BH-4, Room 312" onChange={(e) => set({ residence: e.target.value })} />
        </Field>
        <Field label="Phone">
          <Input type="tel" value={form.phone} maxLength={20} onChange={(e) => set({ phone: e.target.value })} />
        </Field>
        <Field label="Email">
          <Input type="email" value={form.email} maxLength={120} onChange={(e) => set({ email: e.target.value })} />
        </Field>
        <div className="sm:col-span-2">
          <ErrorNote message={error} />
        </div>
      </form>
    </Dialog>
  );
}
