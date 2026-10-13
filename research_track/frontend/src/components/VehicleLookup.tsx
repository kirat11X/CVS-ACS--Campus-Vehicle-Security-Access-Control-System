import { useState } from "react";
import { api } from "../api";
import type { VehicleDetail } from "../types";

export function VehicleLookup() {
  const [plate, setPlate] = useState("");
  const [result, setResult] = useState<VehicleDetail | null>(null);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSearch = async () => {
    if (!plate.trim()) return;
    setLoading(true);
    setSearched(true);
    const data = await api.vehicle(plate.trim());
    setResult(data);
    setLoading(false);
  };

  return (
    <section>
      <h2 className="text-lg font-semibold mb-4">Vehicle Lookup</h2>
      <p className="text-sm text-gray-500 mb-4">
        Displays owner and residence context only after authoritative registry resolution.
        Plate ≠ identity. The system observes; the guard decides.
      </p>

      <div className="flex gap-2 mb-6">
        <input
          type="text"
          value={plate}
          onChange={(e) => setPlate(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Enter plate number (e.g. PB 65 AB 0902)"
          className="flex-1 max-w-md px-4 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-400"
        />
        <button
          onClick={handleSearch}
          disabled={loading}
          className="px-6 py-2 bg-slate-800 text-white rounded-lg hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </div>

      {searched && !loading && (
        <div className="bg-white rounded-lg shadow p-6">
          {result ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-xs text-gray-500 uppercase">Plate</span>
                  <p className="font-mono text-lg">{result.normalizedPlate}</p>
                </div>
                <div>
                  <span className="text-xs text-gray-500 uppercase">Status</span>
                  <p className={result.status === "ACTIVE" ? "text-green-600 font-semibold" : "text-red-600 font-semibold"}>
                    {result.status}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-gray-500 uppercase">Vehicle Type</span>
                  <p>{result.vehicleType}</p>
                </div>
                {result.color && (
                  <div>
                    <span className="text-xs text-gray-500 uppercase">Color</span>
                    <p>{result.color}</p>
                  </div>
                )}
              </div>
              {result.owner && (
                <div className="border-t pt-3 mt-3">
                  <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">
                    Owner Context
                  </h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-xs text-gray-500">Name</span>
                      <p>{result.owner.name}</p>
                    </div>
                    <div>
                      <span className="text-xs text-gray-500">Type</span>
                      <p>{result.owner.personType}</p>
                    </div>
                    {result.owner.department && (
                      <div>
                        <span className="text-xs text-gray-500">Department</span>
                        <p>{result.owner.department}</p>
                      </div>
                    )}
                    {result.owner.residenceType && (
                      <div>
                        <span className="text-xs text-gray-500">Residence</span>
                        <p>
                          {result.owner.residenceType}
                          {result.owner.hostelRoom && ` — ${result.owner.hostelRoom}`}
                          {result.owner.address && ` — ${result.owner.address}`}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-gray-400">No vehicle found for &quot;{plate}&quot; in mock data.</p>
          )}
        </div>
      )}
    </section>
  );
}
