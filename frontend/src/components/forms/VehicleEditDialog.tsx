import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { REGISTRY_ROOTS, useInvalidate } from "../../api/queries";
import type { OwnerContext, VehicleCategory, VehicleDetail, VehicleStatus, VehicleUpdate } from "../../api/types";
import { humanize, toLocalInput } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Callout, ErrorNote } from "../ui/Feedback";
import { Field, Input, Select, Textarea } from "../ui/Form";
import { ALL_CATEGORIES, VEHICLE_STATUSES } from "./options";
import { OwnerSearch } from "./OwnerSearch";

const toInput = (iso: string | null) => (iso ? toLocalInput(new Date(iso)) : "");

/** ADMIN edit of a registration. The plate itself can never change (re-register instead). */
export function VehicleEditDialog({
  token,
  detail,
  onClose,
  onSaved,
}: {
  token: string;
  detail: VehicleDetail;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const v = detail.vehicle;
  const invalidate = useInvalidate();
  const [category, setCategory] = useState<VehicleCategory>(v.category);
  const [status, setStatus] = useState<VehicleStatus>(v.status);
  const [makeModel, setMakeModel] = useState(v.make_model ?? "");
  const [color, setColor] = useState(v.color ?? "");
  const [validFrom, setValidFrom] = useState(toInput(v.valid_from));
  const [validUntil, setValidUntil] = useState(toInput(v.valid_until));
  const [notes, setNotes] = useState(v.notes ?? "");
  const [owner, setOwner] = useState<OwnerContext | null>(detail.owner);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body: VehicleUpdate = {};
    if (category !== v.category) body.vehicle_category = category;
    if (status !== v.status) body.status = status;
    // Text fields: an empty value clears them (stored as empty text).
    if (makeModel.trim() !== (v.make_model ?? "")) body.make_model = makeModel.trim();
    if (color.trim() !== (v.color ?? "")) body.color = color.trim();
    if (notes.trim() !== (v.notes ?? "")) body.notes = notes.trim();
    if (validFrom && validFrom !== toInput(v.valid_from)) body.valid_from = new Date(validFrom).toISOString();
    if (validUntil && validUntil !== toInput(v.valid_until)) body.valid_until = new Date(validUntil).toISOString();
    if (owner && owner.id !== detail.owner?.id) body.owner_id = owner.id;
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.updateVehicle(token, v.plate, body);
      void invalidate(...REGISTRY_ROOTS);
      onSaved(`Updated ${v.plate}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the vehicle.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title={`Edit ${v.plate}`}
      description="The plate cannot be changed. To correct a plate, deactivate this registration and register the vehicle again."
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="vehicle-edit-form" variant="primary" loading={submitting}>
            Save changes
          </Button>
        </>
      }
    >
      <form id="vehicle-edit-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Category">
            <Select value={category} onChange={(e) => setCategory(e.target.value as VehicleCategory)}>
              {ALL_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {humanize(c)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Registry status" hint="Guards see this exactly as recorded.">
            <Select value={status} onChange={(e) => setStatus(e.target.value as VehicleStatus)}>
              {VEHICLE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Valid from">
            <Input type="datetime-local" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
          </Field>
          <Field label="Valid until">
            <Input type="datetime-local" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
          </Field>
          <Field label="Make / model">
            <Input value={makeModel} maxLength={100} onChange={(e) => setMakeModel(e.target.value)} />
          </Field>
          <Field label="Colour">
            <Input value={color} maxLength={50} onChange={(e) => setColor(e.target.value)} />
          </Field>
        </div>
        <fieldset className="space-y-2">
          <legend className="label">Owner</legend>
          <OwnerSearch token={token} selected={owner} onSelect={setOwner} />
          {!owner && detail.owner && <p className="hint">Pick a new owner, or keep the current one ({detail.owner.name}) by closing without saving.</p>}
        </fieldset>
        <Field label="Notes">
          <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        {status === "BLACKLISTED" && v.status !== "BLACKLISTED" && (
          <Callout tone="notice">Guards will see “BLACKLISTED” on every sighting of this plate. The console still makes no access decision.</Callout>
        )}
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
