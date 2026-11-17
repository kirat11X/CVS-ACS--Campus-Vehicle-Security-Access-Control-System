import { ArrowLeftFromLine, ArrowRightToLine, HelpCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { MOVEMENT_ROOTS, useGates, useInvalidate } from "../../api/queries";
import type { Direction, ObservedVehicleType, ResolvedObservation } from "../../api/types";
import { humanize } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { ErrorNote } from "../ui/Feedback";
import { ChoiceGroup, Field, Input, Select, Textarea } from "../ui/Form";

export interface ManualEntryPrefill {
  plate?: string;
  gateId?: string;
}

const VEHICLE_TYPES: ObservedVehicleType[] = ["UNKNOWN", "CAR", "MOTORCYCLE", "BUS", "TRUCK", "BICYCLE"];
// A guard usually works one gate: default to the gate this device last logged at.
const LAST_GATE_KEY = "campus-console.last-gate";

function lastGate(): string | null {
  try {
    return localStorage.getItem(LAST_GATE_KEY);
  } catch {
    return null;
  }
}

export function ManualEntryDialog({
  token,
  prefill,
  onClose,
  onLogged,
}: {
  token: string;
  prefill: ManualEntryPrefill;
  onClose: () => void;
  onLogged: (item: ResolvedObservation) => void;
}) {
  const gates = useGates();
  const invalidate = useInvalidate();
  const [gateId, setGateId] = useState(prefill.gateId ?? "");
  const [plate, setPlate] = useState(prefill.plate ?? "");
  const [direction, setDirection] = useState<Direction | null>(null);
  const [vehicleType, setVehicleType] = useState<ObservedVehicleType>("UNKNOWN");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usable = (gates.data ?? []).filter((g) => g.status !== "INACTIVE" || g.id === gateId);

  useEffect(() => {
    if (gateId || !gates.data) return;
    const remembered = gates.data.find((g) => g.id === lastGate() && g.status === "ACTIVE");
    setGateId(remembered?.id ?? gates.data.find((g) => g.status === "ACTIVE")?.id ?? gates.data[0]?.id ?? "");
  }, [gates.data, gateId]);

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
        vehicle_type: vehicleType,
        note: note.trim() || null,
      });
      try {
        localStorage.setItem(LAST_GATE_KEY, gateId);
      } catch {
        // not remembered; the first active gate stays the default
      }
      void invalidate(...MOVEMENT_ROOTS);
      onLogged(item);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not log the entry.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title="Log manual entry"
      description="Records what you saw as a separate manual sighting under your name. Camera records are not changed."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="manual-entry-form" variant="primary" loading={submitting} disabled={!plate.trim() || !gateId}>
            Log entry
          </Button>
        </>
      }
    >
      <form id="manual-entry-form" onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Plate">
            <Input className="plate" value={plate} maxLength={30} onChange={(e) => setPlate(e.target.value)} required autoCapitalize="characters" autoComplete="off" />
          </Field>
          <Field label="Gate">
            <Select value={gateId} onChange={(e) => setGateId(e.target.value)} required disabled={gates.isLoading}>
              {usable.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.id}){g.status !== "ACTIVE" ? ` · ${humanize(g.status)}` : ""}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <ChoiceGroup<Direction>
          legend="Direction"
          value={direction}
          onChange={setDirection}
          options={[
            { value: "ENTRY", label: "Entry", icon: <ArrowRightToLine className="h-4 w-4" /> },
            { value: "EXIT", label: "Exit", icon: <ArrowLeftFromLine className="h-4 w-4" /> },
            { value: "UNKNOWN", label: "Unknown", icon: <HelpCircle className="h-4 w-4" /> },
          ]}
        />
        <Field label="Vehicle type">
          <Select value={vehicleType} onChange={(e) => setVehicleType(e.target.value as ObservedVehicleType)}>
            {VEHICLE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t === "UNKNOWN" ? "Not recorded" : humanize(t)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Note">
          <Textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        {gates.isError && <ErrorNote message="Could not load gates." />}
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
