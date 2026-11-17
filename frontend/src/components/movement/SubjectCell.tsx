import { Link } from "react-router";
import type { LinkedVehicle, OwnerContext, ResidenceInfo } from "../../api/types";
import { humanize } from "../../lib/format";

/** Plate (links to the vehicle page) with the linked owner, or "Not linked". */
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
        <Link to={`/vehicles/${encodeURIComponent(shown)}`} className="plate text-sm text-slate-900 underline-offset-2 hover:underline dark:text-white">
          {shown}
        </Link>
      ) : (
        <span className="text-sm text-slate-500 dark:text-slate-400">No plate read</span>
      )}
      <div className="truncate text-xs text-slate-600 dark:text-slate-400">
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
