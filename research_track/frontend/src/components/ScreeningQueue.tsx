import { useEffect, useState } from "react";
import { api } from "../api";
import type { ScreeningItem } from "../types";

const OUTCOME_STYLES: Record<string, string> = {
  ALLOW: "bg-green-100 text-green-800",
  REVIEW: "bg-yellow-100 text-yellow-800",
  ALERT: "bg-red-100 text-red-800",
};

export function ScreeningQueue() {
  const [queue, setQueue] = useState<ScreeningItem[]>([]);

  useEffect(() => {
    api.screeningQueue().then(setQueue);
  }, []);

  return (
    <section>
      <h2 className="text-lg font-semibold mb-2">Invoice Screening Review Queue</h2>
      <p className="text-sm text-gray-500 mb-4">
        Line items classified by model with matched policy rule and reason code.
        Approve / Escalate are guard-action stubs — the guard decides.
      </p>

      <div className="space-y-4">
        {queue.map((item, i) => (
          <div key={i} className="bg-white rounded-lg shadow p-4">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-medium">{item.item}</h3>
                <div className="flex gap-3 mt-1 text-sm text-gray-500">
                  <span>Category: <strong>{item.category}</strong></span>
                  <span>Confidence: <strong>{(item.confidence * 100).toFixed(0)}%</strong></span>
                </div>
                <div className="flex gap-3 mt-1 text-sm text-gray-500">
                  <span>Rule: {item.rule}</span>
                  <span>
                    Reason: <code className="bg-gray-100 px-1 rounded">{item.reasonCode}</code>
                  </span>
                </div>
              </div>
              <span
                className={`px-3 py-1 rounded-full text-xs font-semibold ${OUTCOME_STYLES[item.outcome] ?? ""}`}
              >
                {item.outcome}
              </span>
            </div>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => alert(`[UI stub] Guard approved: ${item.item}`)}
                className="px-4 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700"
              >
                Approve (guard stub)
              </button>
              <button
                onClick={() => alert(`[UI stub] Guard escalated: ${item.item}`)}
                className="px-4 py-1.5 text-sm bg-orange-500 text-white rounded hover:bg-orange-600"
              >
                Escalate (guard stub)
              </button>
            </div>
          </div>
        ))}
        {queue.length === 0 && (
          <p className="text-gray-400 text-center py-8">No items in review queue.</p>
        )}
      </div>
    </section>
  );
}
