import { useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { MOVEMENT_ROOTS, useGates, useInvalidate } from "../../api/queries";
import type { Direction } from "../../api/types";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Callout, ErrorNote } from "../ui/Feedback";
import { Field, Input, Select } from "../ui/Form";

// Reads from the mid-term slides: one extra character, not in the registry, one misread character.
const PRESETS = ["CH01AB11234", "UP332KL5567", "HR26DK004Z"];

/** ADMIN-only demo: posts a camera-like sighting (source OTHER) through POST /observations. */
export function SimulatePlateDialog({ token, onClose, onSent }: { token: string; onClose: () => void; onSent: (plate: string) => void }) {
  const gates = useGates();
  const invalidate = useInvalidate();
  const [gateId, setGateId] = useState("");
  const [plate, setPlate] = useState(PRESETS[0]);
  const [confidence, setConfidence] = useState("0.62");
  const [direction, setDirection] = useState<Direction>("ENTRY");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usable = (gates.data ?? []).filter((g) => g.status === "ACTIVE");
  useEffect(() => {
    if (!gateId && usable.length > 0) setGateId((usable.find((g) => g.id === "GATE_2") ?? usable[0]).id);
  }, [gateId, usable]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const conf = Number(confidence);
    if (!Number.isFinite(conf) || conf < 0 || conf > 1) {
      setError("Confidence must be between 0 and 1.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const gate = usable.find((g) => g.id === gateId);
      await api.recordObservation(token, {
        gate_id: gateId,
        camera_id: gate?.camera_id ?? null,
        source: "OTHER",
        source_event_id: `sim-${Date.now().toString(36)}`,
        raw_plate: plate.trim(),
        plate_confidence: conf,
        vehicle_type: "CAR",
        direction,
      });
      void invalidate(...MOVEMENT_ROOTS, "alerts");
      onSent(plate.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send the simulated read.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title="Simulate a plate"
      description="Sends a camera-like read through the normal pipeline so the live feed can be demonstrated without a camera."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="simulate-plate-form" variant="primary" loading={submitting} disabled={!plate.trim() || !gateId}>
            Send read
          </Button>
        </>
      }
    >
      <form id="simulate-plate-form" onSubmit={submit} className="space-y-4">
        <Callout tone="notice">Administrator demo tool. The read is stored as a real sighting (source OTHER) and stays in the history.</Callout>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button key={p} type="button" aria-pressed={plate === p} className={`chip font-mono ${plate === p ? "chip-on" : "chip-off"}`} onClick={() => setPlate(p)}>
              {p}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="OCR read">
            <Input className="plate" value={plate} maxLength={30} onChange={(e) => setPlate(e.target.value.toUpperCase())} required autoComplete="off" />
          </Field>
          <Field label="Gate">
            <Select value={gateId} onChange={(e) => setGateId(e.target.value)} required disabled={gates.isLoading}>
              {usable.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.id})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="OCR confidence (0–1)" hint="Below the server's threshold (0.80 by default) the read needs review and gets close registry matches.">
            <Input type="number" min={0} max={1} step={0.01} value={confidence} onChange={(e) => setConfidence(e.target.value)} />
          </Field>
          <Field label="Sensor direction">
            <Select value={direction} onChange={(e) => setDirection(e.target.value as Direction)}>
              <option value="ENTRY">Entry</option>
              <option value="EXIT">Exit</option>
              <option value="UNKNOWN">Unknown</option>
            </Select>
          </Field>
        </div>
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
