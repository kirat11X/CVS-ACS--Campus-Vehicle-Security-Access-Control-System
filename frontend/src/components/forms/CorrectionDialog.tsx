import { ArrowLeftFromLine, ArrowRightToLine } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { MOVEMENT_ROOTS, useInvalidate } from "../../api/queries";
import type { MovementDirection } from "../../api/types";
import { MOVEMENT_LABEL } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { ErrorNote } from "../ui/Feedback";
import { ChoiceGroup, Field, Input, Textarea } from "../ui/Form";

export interface CorrectionTarget {
  movementId: string;
  direction: MovementDirection;
  plate: string | null;
}

/** Adds a correction row (direction and/or plate). The original record is kept. */
export function CorrectionDialog({
  token,
  target,
  onClose,
  onCorrected,
}: {
  token: string;
  target: CorrectionTarget;
  onClose: () => void;
  onCorrected: () => void;
}) {
  const invalidate = useInvalidate();
  const [direction, setDirection] = useState<MovementDirection>(target.direction);
  const [plate, setPlate] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.correctMovement(token, target.movementId, {
        direction: direction !== target.direction ? direction : undefined,
        plate: plate.trim() || undefined,
        note: note.trim(),
      });
      void invalidate(...MOVEMENT_ROOTS);
      onCorrected();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the correction.");
    } finally {
      setSubmitting(false);
    }
  };

  const unchanged = direction === target.direction && !plate.trim();

  return (
    <Dialog
      title={target.plate ? `Correct movement · ${target.plate}` : "Correct movement · no plate read"}
      description="The original record stays in the log. Your correction is added as a new entry under your name and becomes the current view."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="correction-form" variant="primary" loading={submitting} disabled={unchanged || note.trim().length < 3}>
            Save correction
          </Button>
        </>
      }
    >
      <form id="correction-form" onSubmit={submit} className="space-y-4">
        <ChoiceGroup<MovementDirection>
          legend="Movement"
          value={direction}
          onChange={setDirection}
          options={[
            { value: "ENTRY", label: MOVEMENT_LABEL.ENTRY, icon: <ArrowRightToLine className="h-4 w-4" /> },
            { value: "EXIT", label: MOVEMENT_LABEL.EXIT, icon: <ArrowLeftFromLine className="h-4 w-4" /> },
          ]}
        />
        <Field label={target.plate ? "Corrected plate (optional)" : "Plate read by guard"}>
          <Input className="plate" value={plate} maxLength={30} placeholder={target.plate ?? ""} onChange={(e) => setPlate(e.target.value)} autoCapitalize="characters" autoComplete="off" />
        </Field>
        <Field label="Reason (required)" hint="At least 3 characters, e.g. “Guard saw the car leave, camera read it as entering”.">
          <Textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} required />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
