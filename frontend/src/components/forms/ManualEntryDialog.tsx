import { ArrowLeftFromLine, ArrowRightToLine, Clock, HelpCircle, ShieldAlert, User } from "lucide-react";
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
  isVisitor?: boolean;
}

export const DETAILED_VEHICLE_TYPES: { value: ObservedVehicleType; label: string; description: string }[] = [
  { value: "CAR", label: "Car / SUV / MUV", description: "Sedan, Hatchback, SUV, Taxi" },
  { value: "MOTORCYCLE", label: "Two-Wheeler / Scooter / Apeva", description: "Scooter, Motorcycle, EV Two-Wheeler" },
  { value: "BICYCLE", label: "Bicycle / Cycle (Labor / Worker)", description: "Bicycle (Plate not required)" },
  { value: "TRUCK", label: "Three-Wheeler / Auto / Pickup / Truck", description: "Auto-Rickshaw, LCV, Pickup, Truck" },
  { value: "BUS", label: "Bus / Mini-Bus / Heavy Vehicle", description: "Campus Bus, Heavy Transport" },
  { value: "UNKNOWN", label: "Other / Not Recorded", description: "Unclassified Vehicle" },
];

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
  const [direction, setDirection] = useState<Direction | null>("ENTRY");
  const [vehicleType, setVehicleType] = useState<ObservedVehicleType>("CAR");
  const [note, setNote] = useState("");

  // Guest / Visitor state
  const [isVisitor, setIsVisitor] = useState(prefill.isVisitor ?? false);
  const [visitorName, setVisitorName] = useState("");
  const [visitorPhone, setVisitorPhone] = useState("");
  const [placeOfVisit, setPlaceOfVisit] = useState("");
  const [referencePerson, setReferencePerson] = useState("");
  const [allowedHours, setAllowedHours] = useState<number>(2);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usable = (gates.data ?? []).filter((g) => g.status !== "INACTIVE" || g.id === gateId);
  const isBicycle = vehicleType === "BICYCLE";

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
    if (!isBicycle && !plate.trim()) {
      setError("Plate number is required for motorized vehicles. (Cycles can leave plate blank).");
      return;
    }
    if (isVisitor) {
      if (!visitorName.trim()) {
        setError("Visitor Full Name is required for guest entries.");
        return;
      }
      if (!visitorPhone.trim()) {
        setError("Visitor Mobile Number is required for guest security verification.");
        return;
      }
      if (!placeOfVisit.trim()) {
        setError("Place of Visit / Destination is required (e.g. Department, Hostel, Quarter).");
        return;
      }
    }

    setSubmitting(true);
    setError(null);
    try {
      const item = await api.logManualObservation(token, {
        gate_id: gateId,
        plate: plate.trim() || (isBicycle ? "CYCLE" : `GUEST-${visitorName.trim().slice(0, 6).toUpperCase()}`),
        direction,
        vehicle_type: vehicleType,
        note: note.trim() || (isVisitor ? `Guest entry: ${visitorName.trim()} (${visitorPhone.trim()}) visiting ${placeOfVisit.trim()}` : null),
        is_visitor: isVisitor,
        visitor_name: isVisitor ? visitorName.trim() : undefined,
        visitor_phone: isVisitor ? visitorPhone.trim() : undefined,
        place_of_visit: isVisitor ? placeOfVisit.trim() : undefined,
        reference_person: isVisitor && referencePerson.trim() ? referencePerson.trim() : undefined,
        allowed_duration_hours: isVisitor ? allowedHours : undefined,
      });
      try {
        localStorage.setItem(LAST_GATE_KEY, gateId);
      } catch {
        // storage fallback
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
      title={isVisitor ? "Log Guest / Visitor Entry" : "Log Manual Vehicle Entry"}
      description={
        isVisitor
          ? "Registers a temporary campus guest pass with mobile verification, allotted hours, and automated perimeter overstay alerting."
          : "Records a manual vehicle sighting under your name with exact vehicle classification. Camera records are not changed."
      }
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            form="manual-entry-form"
            variant="primary"
            loading={submitting}
            disabled={(!isBicycle && !plate.trim()) || !gateId || (isVisitor && (!visitorName.trim() || !visitorPhone.trim() || !placeOfVisit.trim()))}
          >
            {isVisitor ? "Issue Guest Pass & Log Entry" : "Log Vehicle Entry"}
          </Button>
        </>
      }
    >
      <form id="manual-entry-form" onSubmit={submit} className="space-y-4">
        {/* Entry Mode Toggle */}
        <div className="flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
          <button
            type="button"
            onClick={() => setIsVisitor(false)}
            className={`flex-1 rounded-md py-1.5 text-xs font-semibold transition-all ${
              !isVisitor
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            }`}
          >
            Standard Vehicle Sighting
          </button>
          <button
            type="button"
            onClick={() => setIsVisitor(true)}
            className={`flex-1 rounded-md py-1.5 text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
              isVisitor
                ? "bg-sky-600 text-white shadow-sm dark:bg-sky-500"
                : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            }`}
          >
            <Clock className="h-3.5 w-3.5" />
            Guest / Visitor Pass (Timed)
          </button>
        </div>

        {/* Guest Pass Specific Fields */}
        {isVisitor && (
          <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3.5 space-y-3 dark:border-sky-900/60 dark:bg-sky-950/20">
            <div className="flex items-center gap-2 text-xs font-semibold text-sky-800 dark:text-sky-300">
              <User className="h-4 w-4 text-sky-600 dark:text-sky-400" />
              <span>Visitor & Security Information</span>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Visitor Full Name" hint="Required">
                <Input
                  value={visitorName}
                  placeholder="e.g. Ramesh Kumar"
                  maxLength={100}
                  onChange={(e) => setVisitorName(e.target.value)}
                  required
                />
              </Field>

              <Field label="Visitor Mobile Number" hint="Required for OTP/Security">
                <Input
                  type="tel"
                  value={visitorPhone}
                  placeholder="e.g. 9876543210"
                  maxLength={15}
                  onChange={(e) => setVisitorPhone(e.target.value)}
                  required
                />
              </Field>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Place of Visit / Destination" hint="Department, Hostel, Quarter">
                <Input
                  value={placeOfVisit}
                  placeholder="e.g. Mechanical Dept / Hostel 4"
                  maxLength={150}
                  onChange={(e) => setPlaceOfVisit(e.target.value)}
                  required
                />
              </Field>

              <Field label="Reference / Host Person (Optional)" hint="Who are they visiting?">
                <Input
                  value={referencePerson}
                  placeholder="e.g. Prof. Sharma / Contractor"
                  maxLength={100}
                  onChange={(e) => setReferencePerson(e.target.value)}
                />
              </Field>
            </div>

            {/* Visitor Allotted Duration Hours */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5 text-sky-600" />
                  Allotted Visiting Hours (From Entry)
                </label>
                <span className="text-xs font-mono font-bold text-sky-700 dark:text-sky-400">
                  {allowedHours} Hour{allowedHours === 1 ? "" : "s"} Allotted
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {[1, 2, 4, 8, 12, 24].map((hrs) => (
                  <button
                    key={hrs}
                    type="button"
                    onClick={() => setAllowedHours(hrs)}
                    className={`px-3 py-1 text-xs rounded-md font-medium transition-all ${
                      allowedHours === hrs
                        ? "bg-sky-600 text-white shadow"
                        : "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700"
                    }`}
                  >
                    {hrs}h
                  </button>
                ))}
              </div>
              <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400 flex items-center gap-1">
                <ShieldAlert className="h-3 w-3 shrink-0" />
                Automatic overstay security alert will trigger if vehicle is inside campus after {allowedHours} hours.
              </p>
            </div>
          </div>
        )}

        {/* Gate & Plate Row */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field
            label={isBicycle ? "Bicycle / Cycle Tag (Optional)" : "License Plate Number"}
            hint={isBicycle ? "Optional for cycle labor" : "Required for motorized vehicles"}
          >
            <Input
              className="plate"
              value={plate}
              maxLength={30}
              placeholder={isBicycle ? "CYCLE (Optional)" : "e.g. CH01AB1234"}
              onChange={(e) => setPlate(e.target.value)}
              required={!isBicycle}
              autoCapitalize="characters"
              autoComplete="off"
            />
          </Field>
          <Field label="Campus Gate">
            <Select value={gateId} onChange={(e) => setGateId(e.target.value)} required disabled={gates.isLoading}>
              {usable.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.id}){g.status !== "ACTIVE" ? ` · ${humanize(g.status)}` : ""}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {/* Direction Selector */}
        <ChoiceGroup<Direction>
          legend="Movement Direction"
          value={direction}
          onChange={setDirection}
          options={[
            { value: "ENTRY", label: "Entry", icon: <ArrowRightToLine className="h-4 w-4" /> },
            { value: "EXIT", label: "Exit", icon: <ArrowLeftFromLine className="h-4 w-4" /> },
            { value: "UNKNOWN", label: "Unknown", icon: <HelpCircle className="h-4 w-4" /> },
          ]}
        />

        {/* Detailed Vehicle Classes Dropdown */}
        <Field label="Vehicle Classification" hint="All classes including Cycles, Scooters, Apeva, Autos, Cars, SUVs, Trucks">
          <Select value={vehicleType} onChange={(e) => setVehicleType(e.target.value as ObservedVehicleType)}>
            {DETAILED_VEHICLE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label} — {t.description}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Security Note / Reason">
          <Textarea rows={2} maxLength={1000} value={note} placeholder="Optional notes for gate record..." onChange={(e) => setNote(e.target.value)} />
        </Field>

        {gates.isError && <ErrorNote message="Could not load gates." />}
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
