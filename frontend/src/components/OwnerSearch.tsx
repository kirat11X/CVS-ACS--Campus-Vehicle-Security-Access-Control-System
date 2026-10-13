import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { OwnerContext } from "../api/types";
import { humanize } from "../lib/format";
import { inputClass } from "./Modal";

interface Props {
  token: string;
  selected: OwnerContext | null;
  onSelect: (owner: OwnerContext | null) => void;
}

/** Debounced search over registered owners (GET /owners?q=). */
export function OwnerSearch({ token, selected, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OwnerContext[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (selected || query.trim().length < 2) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      api
        .searchOwners(token, query.trim(), controller.signal)
        .then(setResults)
        .catch(() => {
          if (!controller.signal.aborted) setResults([]);
        })
        .finally(() => setSearching(false));
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, token, selected]);

  if (selected) {
    return (
      <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-200">
        <span>
          <span className="font-medium">{selected.name}</span> · {selected.institutional_id} · {humanize(selected.residence_type)}
          {selected.residence ? `, ${selected.residence}` : ""}
        </span>
        <button type="button" className="text-xs text-slate-600 underline" onClick={() => onSelect(null)}>
          Change
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <input className={inputClass} placeholder="Name, institutional ID, phone or email" value={query} onChange={(e) => setQuery(e.target.value)} />
      {searching && <p className="text-xs text-slate-500">Searching…</p>}
      {results.length > 0 && (
        <ul className="max-h-40 divide-y divide-slate-100 overflow-y-auto rounded-md ring-1 ring-slate-200">
          {results.map((o) => (
            <li key={o.id}>
              <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-slate-50" onClick={() => onSelect(o)}>
                <span className="font-medium">{o.name}</span>{" "}
                <span className="text-slate-500">
                  {o.institutional_id} · {humanize(o.person_type)} · {humanize(o.residence_type)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!searching && query.trim().length >= 2 && results.length === 0 && <p className="text-xs text-slate-500">No matching owners.</p>}
    </div>
  );
}
