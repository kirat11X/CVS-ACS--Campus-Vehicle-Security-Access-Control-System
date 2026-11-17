import { UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { OwnerContext, PersonType } from "../../api/types";
import { humanize } from "../../lib/format";
import { SearchInput } from "../ui/Form";
import { Spinner } from "../ui/Feedback";

/**
 * Debounced search over registered owners (GET /owners?q=), by name, SID / employee ID, phone or email.
 * `personType` narrows to students, faculty or staff; an exact ID match on `initialQuery` is preselected.
 */
export function OwnerSearch({
  token,
  selected,
  onSelect,
  initialQuery = "",
  personType = null,
}: {
  token: string;
  selected: OwnerContext | null;
  onSelect: (owner: OwnerContext | null) => void;
  initialQuery?: string;
  personType?: PersonType | null;
}) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<OwnerContext[]>([]);
  const [searching, setSearching] = useState(false);
  // Refs: the auto-pick runs once, and a caller's inline onSelect must not restart the search.
  const autoPick = useRef(initialQuery.trim());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (selected || query.trim().length < 2) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      api
        .searchOwners(token, query.trim(), controller.signal, personType)
        .then((found) => {
          setResults(found);
          // A typed SID / employee ID that matches exactly one owner is the guard's intent; still shown and changeable.
          const wanted = autoPick.current.toLowerCase();
          if (wanted) {
            autoPick.current = "";
            const exact = found.filter((o) => o.institutional_id.toLowerCase() === wanted);
            if (exact.length === 1) onSelectRef.current(exact[0]);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) setResults([]);
        })
        .finally(() => setSearching(false));
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, token, selected, personType]);

  if (selected) {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2.5 text-sm ring-1 ring-slate-200 dark:bg-slate-800/60 dark:ring-slate-700">
        <UserRound className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="font-medium text-slate-900 dark:text-white">{selected.name}</span>
          <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
            {selected.institutional_id} · {humanize(selected.person_type)} · {humanize(selected.residence_type)}
            {selected.residence ? `, ${selected.residence}` : ""}
            {selected.department ? ` · ${selected.department}` : ""}
          </span>
        </span>
        <button type="button" className="link text-xs" onClick={() => onSelect(null)}>
          Change
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <SearchInput
        label="Search owners"
        placeholder={personType === "STUDENT" ? "SID (e.g. 2410xxxx) or name" : "Name, SID / employee ID, phone or email"}
        value={query}
        onChange={setQuery}
      />
      {searching && <Spinner label="Searching…" />}
      {results.length > 0 && (
        <ul className="max-h-48 divide-y divide-slate-100 overflow-y-auto rounded-lg ring-1 ring-slate-200 dark:divide-slate-800 dark:ring-slate-700">
          {results.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                className="w-full px-3 py-2.5 text-left text-sm hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-none dark:hover:bg-slate-800 dark:focus-visible:bg-slate-800"
                onClick={() => onSelect(o)}
              >
                <span className="font-medium text-slate-900 dark:text-white">{o.name}</span>
                <span className="block text-xs text-slate-500 dark:text-slate-400">
                  {o.institutional_id} · {humanize(o.person_type)} · {humanize(o.residence_type)}
                  {o.department ? ` · ${o.department}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!searching && query.trim().length >= 2 && results.length === 0 && (
        <p className="hint">No matching {personType ? `${humanize(personType).toLowerCase()} ` : ""}owners. Use “New owner” to record them.</p>
      )}
    </div>
  );
}
