import { useEffect, useState } from "react";
import { api } from "../api";
import type { Observation } from "../types";

export function GateFeed() {
  const [observations, setObservations] = useState<Observation[]>([]);

  useEffect(() => {
    api.observations().then(setObservations);
  }, []);

  return (
    <section>
      <h2 className="text-lg font-semibold mb-4">Gate Observations</h2>
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white rounded-lg shadow">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Gate</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Plate</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Confidence</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Vehicle Type</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Direction</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {observations.map((o) => (
              <tr key={o.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm">{o.gateId ?? "—"}</td>
                <td className="px-4 py-3 text-sm font-mono">
                  {o.plate ?? <span className="text-gray-400 italic">Not read</span>}
                </td>
                <td className="px-4 py-3 text-sm">
                  {o.confidence != null ? `${(o.confidence * 100).toFixed(1)}%` : "—"}
                </td>
                <td className="px-4 py-3 text-sm">{o.vehicleType}</td>
                <td className="px-4 py-3 text-sm">
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-xs ${
                      o.direction === "UNKNOWN"
                        ? "bg-yellow-100 text-yellow-800"
                        : "bg-green-100 text-green-800"
                    }`}
                  >
                    {o.direction === "UNKNOWN" ? "UNKNOWN (not inferred)" : o.direction}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500">
                  {new Date(o.observedAt).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {observations.length === 0 && (
        <p className="text-gray-400 text-center py-8">No observations loaded.</p>
      )}
    </section>
  );
}
