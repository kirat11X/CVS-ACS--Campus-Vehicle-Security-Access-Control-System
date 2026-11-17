import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { useInvalidate } from "../../api/queries";
import type { Gate, GateStatus } from "../../api/types";
import { humanize } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { ErrorNote } from "../ui/Feedback";
import { Field, Input, Select } from "../ui/Form";
import { GATE_STATUSES, blankToNull } from "./options";

/** Create (gate = null) or edit a gate. ADMIN only. Gates are retired (INACTIVE), never deleted. */
export function GateFormDialog({ token, gate, onClose, onSaved }: { token: string; gate: Gate | null; onClose: () => void; onSaved: (m: string) => void }) {
  const invalidate = useInvalidate();
  const [form, setForm] = useState({
    id: gate?.id ?? "",
    name: gate?.name ?? "",
    location: gate?.location ?? "",
    camera_id: gate?.camera_id ?? "",
    status: (gate?.status ?? "ACTIVE") as GateStatus,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (gate) {
        await api.updateGate(token, gate.id, {
          name: form.name.trim(),
          location: blankToNull(form.location),
          status: form.status,
          ...(form.camera_id.trim() !== (gate.camera_id ?? "") && form.camera_id.trim() ? { camera_id: form.camera_id.trim() } : {}),
        });
      } else {
        await api.createGate(token, {
          id: form.id.trim().toUpperCase(),
          name: form.name.trim(),
          location: blankToNull(form.location),
          camera_id: blankToNull(form.camera_id),
          status: form.status,
        });
      }
      void invalidate("gates", "lanes", "dashboard");
      onSaved(gate ? `Updated ${gate.name}.` : `Added ${form.name.trim()}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the gate.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title={gate ? `Edit ${gate.name}` : "Add gate"}
      description="A gate maps one Frigate camera to a campus entry point. Gates hold no decision logic."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="gate-form" variant="primary" loading={submitting} disabled={!form.name.trim() || !form.id.trim()}>
            {gate ? "Save changes" : "Add gate"}
          </Button>
        </>
      }
    >
      <form id="gate-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Gate ID" hint={gate ? "Cannot be changed." : "e.g. GATE_4"}>
            <Input value={form.id} maxLength={30} required disabled={!!gate} className="font-mono uppercase" onChange={(e) => set({ id: e.target.value })} />
          </Field>
          <Field label="Name">
            <Input value={form.name} maxLength={100} required onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="Frigate camera ID" hint="The camera name in Frigate's config.yml">
            <Input value={form.camera_id} maxLength={50} className="font-mono" onChange={(e) => set({ camera_id: e.target.value })} />
          </Field>
          <Field label="Status">
            <Select value={form.status} onChange={(e) => set({ status: e.target.value as GateStatus })}>
              {GATE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Location">
          <Input value={form.location} maxLength={200} onChange={(e) => set({ location: e.target.value })} />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
