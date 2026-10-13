import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import type { MovementDirection } from "../../api/types";
import { MOVEMENT_LABEL } from "../../lib/format";
import { ErrorNote, Field, Modal, inputClass, primaryButton, secondaryButton } from "../Modal";

export interface CorrectionTarget {
  movementId: string;
  direction: MovementDirection;
  plate: string | null;
}

interface Props {
  token: string;
  target: CorrectionTarget;
  onClose: () => void;
  onCorrected: () => void;
}

/** Adds a correction row (direction and/or plate). The original record is kept. */
export function CorrectionModal({ token, target, onClose, onCorrected }: Props) {
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
      onCorrected();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the correction.");
    } finally {
      setSubmitting(false);
    }
  };

  const unchanged = direction === target.direction && !plate.trim();

  return (
    <Modal
      title={target.plate ? `Correct movement · ${target.plate}` : "Correct movement · no plate read"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="correction-form" className={primaryButton} disabled={submitting || unchanged || note.trim().length < 3}>
            {submitting ? "Saving…" : "Save correction"}
          </button>
        </>
      }
    >
      <form id="correction-form" onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-600">
          The original record stays in the log. Your correction is added as a new entry under your name and becomes the current view.
        </p>
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Movement</legend>
          <div className="mt-1 flex gap-2" role="radiogroup">
            {(["ENTRY", "EXIT"] as MovementDirection[]).map((d) => (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={direction === d}
                className={`${secondaryButton} ${direction === d ? "bg-slate-800 text-white hover:bg-slate-700" : ""}`}
                onClick={() => setDirection(d)}
              >
                {MOVEMENT_LABEL[d]}
              </button>
            ))}
          </div>
        </fieldset>
        <Field label={target.plate ? "Corrected plate (optional)" : "Plate read by guard"}>
          <input
            className={inputClass + " font-mono uppercase"}
            value={plate}
            maxLength={30}
            placeholder={target.plate ?? ""}
            onChange={(e) => setPlate(e.target.value)}
          />
        </Field>
        <Field label="Reason (required)">
          <textarea className={inputClass} rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} required />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Modal>
  );
}
