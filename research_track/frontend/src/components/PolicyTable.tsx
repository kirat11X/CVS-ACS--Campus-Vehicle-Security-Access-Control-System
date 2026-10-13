import { useEffect, useState } from "react";
import { api } from "../api";
import type { PolicyRule } from "../types";

const ACTION_STYLES: Record<string, string> = {
  ALLOW: "text-green-700 bg-green-50",
  REVIEW: "text-yellow-700 bg-yellow-50",
  ALERT: "text-red-700 bg-red-50",
};

export function PolicyTable() {
  const [rules, setRules] = useState<PolicyRule[]>([]);

  useEffect(() => {
    api.screeningPolicy().then(setRules);
  }, []);

  return (
    <section>
      <h2 className="text-lg font-semibold mb-2">Screening Policy Rules</h2>
      <p className="text-sm text-gray-500 mb-4">
        Read-only view of the deterministic policy table. Policy edits require a versioned
        server-side review process.
      </p>

      <div className="overflow-x-auto">
        <table className="min-w-full bg-white rounded-lg shadow">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Category</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Condition</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reason Code</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Version</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {rules.map((r) => (
              <tr key={r.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm font-medium">{r.category}</td>
                <td className="px-4 py-3 text-sm">
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${ACTION_STYLES[r.action] ?? ""}`}>
                    {r.action}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{r.condition}</td>
                <td className="px-4 py-3 text-sm">
                  <code className="bg-gray-100 px-1 rounded text-xs">{r.reasonCode}</code>
                </td>
                <td className="px-4 py-3 text-sm text-center">{r.priority}</td>
                <td className="px-4 py-3 text-sm text-gray-500">{r.policyVersion}</td>
                <td className="px-4 py-3 text-sm">
                  {r.active ? "✓" : "✗"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4">
        <button
          disabled
          className="px-4 py-2 bg-gray-300 text-gray-500 rounded cursor-not-allowed text-sm font-medium"
        >
          Edit Policy (stub — versioned server-side review required)
        </button>
      </div>
    </section>
  );
}
