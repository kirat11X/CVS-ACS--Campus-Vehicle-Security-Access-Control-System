import { useState, type FormEvent } from "react";
import { ApiError, api } from "../../api/client";
import { useInvalidate } from "../../api/queries";
import type { Gate, Lane, LaneRole } from "../../api/types";
import { LANE_ROLE_LABEL } from "../../lib/format";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Callout, ErrorNote } from "../ui/Feedback";
import { ChoiceGroup, Field, Input, Select, Switch, Textarea } from "../ui/Form";
import { blankToNull } from "./options";

/**
 * Declares which way traffic passes a camera (ADMIN). This is site configuration entered
 * by a person; the system never infers direction from a camera or gate name.
 */
export function LaneFormDialog({
  token,
  lane,
  gates,
  defaultCamera,
  defaultGate,
  onClose,
  onSaved,
}: {
  token: string;
  lane: Lane | null;
  gates: Gate[];
  defaultCamera?: string;
  defaultGate?: string;
  onClose: () => void;
  onSaved: (m: string) => void;
}) {
  const invalidate = useInvalidate();
  const live = gates.filter((g) => g.status !== "INACTIVE");
  const [camera, setCamera] = useState(lane?.camera_id ?? defaultCamera ?? "");
  const [gateId, setGateId] = useState(lane?.gate_id ?? defaultGate ?? live[0]?.id ?? "");
  const [role, setRole] = useState<LaneRole>(lane?.lane_role ?? "ENTRY_LANE");
  const [outside, setOutside] = useState(lane?.outside_zone ?? "");
  const [inside, setInside] = useState(lane?.inside_zone ?? "");
  const [active, setActive] = useState(lane?.is_active ?? true);
  const [notes, setNotes] = useState(lane?.notes ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const zonesHalfSet = role === "BIDIRECTIONAL" && !!outside.trim() !== !!inside.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.upsertLane(token, camera.trim(), {
        gate_id: gateId,
        lane_role: role,
        outside_zone: role === "BIDIRECTIONAL" ? blankToNull(outside) : null,
        inside_zone: role === "BIDIRECTIONAL" ? blankToNull(inside) : null,
        is_active: active,
        notes: blankToNull(notes),
      });
      void invalidate("lanes", "gates", "dashboard");
      onSaved(`Lane for ${camera.trim()} saved.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the lane.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      title={lane ? `Lane · ${lane.camera_id}` : "Declare camera lane"}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="lane-form" variant="primary" loading={submitting} disabled={!camera.trim() || !gateId || zonesHalfSet}>
            Save lane
          </Button>
        </>
      }
    >
      <form id="lane-form" onSubmit={submit} className="space-y-4">
        <Callout>
          Direction is only ever taken from a lane role declared here, a declared zone order, or a guard's confirmation. Without one, sightings stay
          direction-unknown and no movement is logged.
        </Callout>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Frigate camera ID" hint={lane ? "Cannot be changed." : undefined}>
            <Input value={camera} maxLength={50} required disabled={!!lane} className="font-mono" onChange={(e) => setCamera(e.target.value)} />
          </Field>
          <Field label="Gate">
            <Select value={gateId} onChange={(e) => setGateId(e.target.value)} required>
              {live.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.id})
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <ChoiceGroup<LaneRole>
          legend="Lane role"
          value={role}
          onChange={setRole}
          options={(["ENTRY_LANE", "EXIT_LANE", "BIDIRECTIONAL"] as LaneRole[]).map((r) => ({ value: r, label: LANE_ROLE_LABEL[r] }))}
          hint={
            role === "BIDIRECTIONAL"
              ? "Two-way lanes need both Frigate zone names; the order a vehicle enters them gives the direction."
              : "Every sighting on this camera is logged as this direction."
          }
        />
        {role === "BIDIRECTIONAL" && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Outside zone (road side)">
              <Input value={outside} maxLength={64} className="font-mono" placeholder="road_side" onChange={(e) => setOutside(e.target.value)} />
            </Field>
            <Field label="Inside zone (campus side)">
              <Input value={inside} maxLength={64} className="font-mono" placeholder="campus_side" onChange={(e) => setInside(e.target.value)} />
            </Field>
            {zonesHalfSet && <p className="hint sm:col-span-2">Give both zones, or neither.</p>}
          </div>
        )}
        <Switch checked={active} onChange={setActive} label="Active" description="Retire a lane by turning this off; lanes are never deleted." />
        <Field label="Notes">
          <Textarea rows={2} maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <ErrorNote message={error} />
      </form>
    </Dialog>
  );
}
