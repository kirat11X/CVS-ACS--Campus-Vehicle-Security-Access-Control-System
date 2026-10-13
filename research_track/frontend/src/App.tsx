import { useState } from "react";
import { GateFeed } from "./components/GateFeed";
import { VehicleLookup } from "./components/VehicleLookup";
import { ScreeningQueue } from "./components/ScreeningQueue";
import { PolicyTable } from "./components/PolicyTable";
import { EvalMetrics } from "./components/EvalMetrics";

type Page = "live" | "vehicle" | "queue" | "policy" | "eval";

const NAV: { id: Page; label: string }[] = [
  { id: "live", label: "Gate Live Feed" },
  { id: "vehicle", label: "Vehicle Lookup" },
  { id: "queue", label: "Invoice Review Queue" },
  { id: "policy", label: "Policy Table" },
  { id: "eval", label: "Model Evaluation" },
];

export function App() {
  const [page, setPage] = useState<Page>("live");

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-slate-800 text-white px-6 py-4">
        <h1 className="text-xl font-bold">PEC Campus Security — Research Dashboard</h1>
        <p className="text-sm text-slate-300 mt-1">
          Context and flags only — guards decide. This UI never controls barriers.
        </p>
      </header>

      <nav className="bg-white border-b px-6 py-2 flex gap-2 overflow-x-auto">
        {NAV.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setPage(id)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              page === id
                ? "bg-slate-800 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {page === "live" && <GateFeed />}
        {page === "vehicle" && <VehicleLookup />}
        {page === "queue" && <ScreeningQueue />}
        {page === "policy" && <PolicyTable />}
        {page === "eval" && <EvalMetrics />}
      </main>

      <footer className="text-center text-xs text-gray-400 py-4">
        Research staging UI · No live data connections in mock mode
      </footer>
    </div>
  );
}
