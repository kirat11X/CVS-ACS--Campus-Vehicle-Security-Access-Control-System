import type { LinkedVehicle, OwnerContext, ResidenceInfo } from "../../api/types";
import { humanize } from "../../lib/format";
import { navigate } from "../../lib/route";

/** Plate (links to history) with the linked owner, or "Not linked". */
export function SubjectCell({
  plate,
  vehicle,
  owner,
  residence,
}: {
  plate: string | null;
  vehicle: LinkedVehicle | null;
  owner: OwnerContext | null;
  residence: ResidenceInfo | null;
}) {
  const shown = vehicle?.plate ?? plate;
  return (
    <div className="min-w-0">
      {shown ? (
        <button type="button" className="font-mono text-sm font-semibold text-slate-900 underline-offset-2 hover:underline" onClick={() => navigate("history", shown)}>
          {shown}
        </button>
      ) : (
        <span className="text-sm text-slate-500">No plate read</span>
      )}
      <div className="truncate text-xs text-slate-600">
        {owner ? (
          <>
            {owner.name} · {owner.institutional_id}
            {residence?.residence_type ? ` · ${humanize(residence.residence_type)}` : ""}
            {residence?.residence ? `, ${residence.residence}` : ""}
          </>
        ) : vehicle ? (
          `${humanize(vehicle.category)} · no owner on record`
        ) : (
          "Not linked"
        )}
      </div>
    </div>
  );
}
