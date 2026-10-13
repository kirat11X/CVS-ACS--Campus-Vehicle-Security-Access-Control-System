import { useCallback, useMemo, useState } from "react";
import type { LinkStatus, ResolvedObservation, Role } from "../api/types";
import type { FeedCard } from "../feed/useLiveFeed";
import { LINK_STATUS_LABEL } from "../lib/format";
import { ManualEntryModal } from "./ManualEntryModal";
import { ObservationCard, type ManualEntryPrefill } from "./ObservationCard";
import { RegisterVehicleModal } from "./RegisterVehicleModal";
import { inputClass, primaryButton } from "./Modal";
import { CorrectionModal, type CorrectionTarget } from "./movement/CorrectionModal";
import { LinkOwnerModal } from "./movement/LinkOwnerModal";

type Dialog =
  | { type: "register"; plate: string }
  | { type: "link"; plate: string }
  | { type: "manual"; prefill: ManualEntryPrefill }
  | { type: "correct"; target: CorrectionTarget }
  | null;

const STATUS_FILTERS: (LinkStatus | "ALL")[] = ["ALL", "LOW_CONFIDENCE", "NOT_LINKED", "LINKED_INACTIVE", "LINKED", "NO_PLATE"];

interface Props {
  token: string;
  role: Role;
  cards: FeedCard[];
  loading: boolean;
  upsertItem: (item: ResolvedObservation, kind: FeedCard["kind"]) => void;
  notify: (message: string) => void;
}

export function FeedPage({ token, role, cards, loading, upsertItem, notify }: Props) {
  const [dialog, setDialog] = useState<Dialog>(null);
  const [gateFilter, setGateFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState<LinkStatus | "ALL">("ALL");

  const gates = useMemo(() => {
    const seen = new Map<string, string>();
    for (const c of cards) seen.set(c.item.observation.gate.id, c.item.observation.gate.name);
    return [...seen.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [cards]);

  const visible = cards.filter(
    (c) =>
      (gateFilter === "ALL" || c.item.observation.gate.id === gateFilter) &&
      (statusFilter === "ALL" || c.item.link_status === statusFilter),
  );

  const counts = useMemo(() => {
    const out: Partial<Record<LinkStatus, number>> = {};
    for (const c of cards) out[c.item.link_status] = (out[c.item.link_status] ?? 0) + 1;
    return out;
  }, [cards]);

  const closeDialog = useCallback(() => setDialog(null), []);
  const onResolved = useCallback((item: ResolvedObservation) => upsertItem(item, "RESOLUTION_ADDED"), [upsertItem]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select className={inputClass + " w-auto py-1 text-xs"} value={gateFilter} onChange={(e) => setGateFilter(e.target.value)} aria-label="Gate">
          <option value="ALL">All gates</option>
          {gates.map(([id, name]) => (
            <option key={id} value={id}>
              {name} ({id})
            </option>
          ))}
        </select>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatusFilter(s)}
            className={`rounded-full px-2.5 py-1 text-xs ring-1 ${
              statusFilter === s ? "bg-slate-800 text-white ring-slate-800" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"
            }`}
          >
            {s === "ALL" ? `All (${cards.length})` : `${LINK_STATUS_LABEL[s]} (${counts[s] ?? 0})`}
          </button>
        ))}
        <button type="button" className={primaryButton + " ml-auto"} onClick={() => setDialog({ type: "manual", prefill: {} })}>
          Log manual entry
        </button>
      </div>

      {visible.length === 0 ? (
        <p className="py-16 text-center text-sm text-slate-500">
          {loading ? "Loading…" : "No observations to show yet. New camera sightings appear here as they arrive."}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {visible.map((card) => (
            <ObservationCard
              key={card.item.observation.id}
              token={token}
              card={card}
              onRegister={(plate) => setDialog({ type: "register", plate })}
              onLink={(plate) => setDialog({ type: "link", plate })}
              onManualEntry={(prefill) => setDialog({ type: "manual", prefill })}
              onCorrect={(target) => setDialog({ type: "correct", target })}
              onResolved={onResolved}
            />
          ))}
        </div>
      )}

      {dialog?.type === "register" && (
        <RegisterVehicleModal
          token={token}
          role={role}
          plate={dialog.plate}
          onClose={closeDialog}
          onRegistered={(message) => {
            setDialog(null);
            notify(message);
          }}
        />
      )}
      {dialog?.type === "link" && (
        <LinkOwnerModal
          token={token}
          role={role}
          plate={dialog.plate}
          onClose={closeDialog}
          onLinked={(message) => {
            setDialog(null);
            notify(message);
          }}
        />
      )}
      {dialog?.type === "manual" && (
        <ManualEntryModal
          token={token}
          prefill={dialog.prefill}
          onClose={closeDialog}
          onLogged={(item) => {
            upsertItem(item, "OBSERVATION_CREATED");
            setDialog(null);
            notify(`Manual entry logged for ${item.observation.plate.normalized}.`);
          }}
        />
      )}
      {dialog?.type === "correct" && (
        <CorrectionModal
          token={token}
          target={dialog.target}
          onClose={closeDialog}
          onCorrected={() => {
            setDialog(null);
            notify("Correction recorded.");
          }}
        />
      )}
    </>
  );
}
