import { useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import type { Direction, Gate, ResolvedObservation } from "../api/types";
import { ErrorNote, Field, Modal, inputClass, primaryButton, secondaryButton } from "./Modal";
import type { ManualEntryPrefill } from "./ObservationCard";

const DIRECTIONS: { value: Direction; label: string }[] = [
  { value: "ENTRY", label: "Entry" },
  { value: "EXIT", label: "Exit" },
  { value: "UNKNOWN", label: "Unknown" },
];

interface Props {
  token: string;
  prefill: ManualEntryPrefill;
  onClose: () => void;
  onLogged: (item: ResolvedObservation) => void;
}

export function ManualEntryModal({ token, prefill, onClose, onLogged }: Props) {
  const [gates, setGates] = useState<Gate[]>([]);
  const [gateId, setGateId] = useState(prefill.gateId ?? "");
  const [plate, setPlate] = useState(prefill.plate ?? "");
  const [direction, setDirection] = useState<Direction | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .gates()
      .then((list) => {
        setGates(list);
        setGateId((current) => current || list.find((g) => g.status === "ACTIVE")?.id || list[0]?.id || "");
      })
      .catch(() => setError("Could not load gates."));
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!direction) {
      setError("Choose a direction. Pick Unknown if you could not tell.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const item = await api.logManualObservation(token, {
        gate_id: gateId,
        plate: plate.trim(),
        direction,
        note: note.trim() || null,
      });
      onLogged(item);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not log the entry.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="Log manual entry"
      onClose={onClose}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="manual-entry-form" className={primaryButton} disabled={submitting || !plate.trim() || !gateId}>
            {submitting ? "Saving…" : "Log entry"}
          </button>
        </>
      }
    >
      <form id="manual-entry-form" onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-600">
          Records what you saw as a separate manual sighting under your name. Camera records are not changed.
        </p>
        <Field label="Gate">
          <select className={inputClass} value={gateId} onChange={(e) => setGateId(e.target.value)} required>
            {gates.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name} ({g.id}){g.status !== "ACTIVE" ? ` · ${g.status}` : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Plate">
          <input className={inputClass + " font-mono uppercase"} value={plate} maxLength={30} onChange={(e) => setPlate(e.target.value)} required />
        </Field>
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Direction</legend>
          <div className="mt-1 flex gap-2" role="radiogroup">
            {DIRECTIONS.map((d) => (
              <button
                key={d.value}
                type="button"
                role="radio"
                aria-checked={direction === d.value}
                className={`${secondaryButton} ${direction === d.value ? "bg-slate-800 text-white hover:bg-slate-700" : ""}`}
                onClick={() => setDirection(d.value)}
              >
                {d.label}
              </button>
            ))}
          </div>
        </fieldset>
        <Field label="Note">
          <textarea className={inputClass} rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Modal>
  );
}
