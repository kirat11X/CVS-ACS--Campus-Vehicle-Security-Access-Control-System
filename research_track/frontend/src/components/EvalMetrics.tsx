import { useEffect, useState } from "react";
import { api } from "../api";
import type { EvalMetrics as EvalMetricsType } from "../types";

export function EvalMetrics() {
  const [metrics, setMetrics] = useState<EvalMetricsType | null>(null);

  useEffect(() => {
    api.evaluation().then(setMetrics);
  }, []);

  return (
    <section>
      <h2 className="text-lg font-semibold mb-2">Model Evaluation Metrics</h2>
      <p className="text-sm text-gray-500 mb-4">
        Static JSON from the latest evaluation run. No model was loaded or executed to produce
        this view.
      </p>

      {metrics ? (
        <pre className="bg-white rounded-lg shadow p-6 overflow-x-auto text-sm font-mono text-gray-700">
          {JSON.stringify(metrics, null, 2)}
        </pre>
      ) : (
        <p className="text-gray-400 text-center py-8">No evaluation data loaded.</p>
      )}
    </section>
  );
}
