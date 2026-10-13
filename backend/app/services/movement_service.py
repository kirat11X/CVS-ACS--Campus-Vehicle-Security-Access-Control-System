from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence
from uuid import UUID
from sqlalchemy.orm import Session, selectinload

from backend.app.config import MOVEMENT_DEBOUNCE_SECONDS, PRESENCE_LONG_STAY_HOURS, PRESENCE_UNATTRIBUTED_LOOKBACK_HOURS
from backend.app.models.enums import (
    DirectionMethod,
    FeedEventKind,
    GateDirection,
    LinkStatus,
    LogPlateSource,
    ObservationDirection,
    ObservationSource,
    PresenceStatus,
)
from backend.app.models.gate import EntryExitLog
from backend.app.models.movement import VehicleLinkEvent
from backend.app.models.observation import ObservationEvent, ObservationResolution
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.feed import LinkedVehicle, ResidenceInfo, UserSummary
from backend.app.schemas.movement import (
    InsideResponse,
    LinkEventResponse,
    MovementDetail,
    MovementEntry,
    MovementLogRow,
    MovementPage,
    PresenceEntry,
    PresencePage,
    TimelineItem,
    VehicleHistory,
)
from backend.app.schemas.observation import GateSummary
from backend.app.schemas.vehicle import OwnerContextResponse
from backend.app.services.direction_resolver import DirectionResult, direction_resolver
from backend.app.services.feed_events import record_feed_event
from backend.app.services.identity_resolution_service import identity_resolution_service
from backend.app.services.movement_lookup import Movement, load_movement, load_movements, movement_roots
from backend.app.services.plate_normalizer import normalize_plate

class MovementError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

def _user(user) -> Optional[UserSummary]:
    if user is None:
        return None
    return UserSummary(id=user.id, username=user.username, full_name=user.full_name, role=user.role)

@dataclass
class _Attribution:
    vehicle: Optional[LinkedVehicle] = None
    owner: Optional[OwnerContextResponse] = None
    residence: Optional[ResidenceInfo] = None
    basis: Optional[str] = None
    low_confidence: bool = False

@dataclass
class _Row:
    movement: Movement
    attribution: _Attribution
    subject: Optional[str]
    flags: List[str] = field(default_factory=list)

    @property
    def sort_key(self):
        return (self.movement.timestamp, self.movement.root.created_at)

class MovementService:
    """
    Phase 6 movement log over entry_exit_logs.

    Write side: a root row is created only when DirectionResolver (declared lane role,
    declared zone order, or a guard) yields ENTRY/EXIT; one root per observation
    (unique observation_id). Changes are correction rows pointing at the root;
    nothing is updated or deleted. Movement rows carry no access decision.

    Read side: presence, flags and owner attribution are computed on every read.
    Observation-sourced plates are attributed through the Phase 5C resolver (so later
    registrations and guard resolutions apply retroactively); guard-corrected plates
    are joined to the registry by exact plate.
    """

    # ------------------------------------------------------------------ write side

    def on_observation(self, db: Session, obs: ObservationEvent) -> Optional[EntryExitLog]:
        """Called inside the ingestion transaction after the observation is flushed."""
        root = db.query(EntryExitLog).filter(EntryExitLog.observation_id == obs.id).first()
        if root is not None:
            self._sensor_refinement(db, root, obs)
            return root

        result = direction_resolver.resolve(db, obs)
        if not result.is_known:
            return None  # UNKNOWN never creates a movement
        human = obs.source == ObservationSource.MANUAL
        if not human and self._repeat_of_recent(db, obs, result.direction.value):
            return None
        return self._create_root(db, obs, result, created_by_id=obs.created_by_id if human else None, note=None)

    def confirm_direction(self, db: Session, observation_id: UUID, direction: str, note: Optional[str], user_id: UUID) -> Movement:
        """Guard confirms ENTRY/EXIT for an observation that has no movement yet."""
        obs = db.query(ObservationEvent).filter(ObservationEvent.id == observation_id).with_for_update().first()
        if obs is None:
            raise MovementError(404, f"Observation '{observation_id}' not found.")
        if db.query(EntryExitLog.id).filter(EntryExitLog.observation_id == obs.id).first():
            raise MovementError(409, "This observation already has a movement record; submit a correction instead.")
        derived = direction_resolver.resolve(db, obs)
        result = DirectionResult(
            ObservationDirection(direction), DirectionMethod.GUARD_CONFIRMED, None,
            {"confirmed_by_id": str(user_id), "derived_before_confirmation": derived.as_dict()},
        )
        root = self._create_root(db, obs, result, created_by_id=user_id, note=note)
        record_feed_event(db, obs.id, FeedEventKind.MOVEMENT_UPDATED)
        db.commit()
        return load_movement(db, root.id)

    def correct(self, db: Session, log_id: UUID, direction: Optional[str], plate: Optional[str], note: str, user_id: UUID) -> Movement:
        """Appends a correction row (wrong direction and/or plate). The original rows stay."""
        row = db.get(EntryExitLog, log_id)
        if row is None or row.direction_method is None:
            raise MovementError(404, f"Movement '{log_id}' not found.")
        root = (
            db.query(EntryExitLog)
            .filter(EntryExitLog.id == (row.correction_of_id or row.id))
            .with_for_update()  # serialises corrections of one movement; no UPDATE is issued
            .one()
        )
        eff = load_movements(db, [root])[0].effective

        overrides = {"created_by_id": user_id, "note": note}
        changed = False
        if direction is not None and direction != eff.direction.value:
            overrides.update(
                direction=GateDirection(direction),
                direction_method=DirectionMethod.GUARD_CONFIRMED,
                direction_confidence=None,
                direction_evidence={"corrected_from": eff.direction.value, "previous_method": eff.direction_method.value},
            )
            changed = True
        if plate is not None:
            norm = normalize_plate(plate)
            if not norm:
                raise MovementError(400, "Plate must contain at least one letter or digit.")
            if norm != eff.normalized_plate:
                vehicle = db.query(Vehicle).filter(Vehicle.normalized_plate == norm).first()
                overrides.update(
                    plate=plate.strip(), normalized_plate=norm, plate_source=LogPlateSource.GUARD_CORRECTION,
                    confidence=None, vehicle_id=vehicle.id if vehicle else None,
                )
                changed = True
        if not changed:
            raise MovementError(400, "The correction does not change the direction or the plate.")

        db.add(self._correction_from(eff, root, **overrides))
        if root.observation_id:
            record_feed_event(db, root.observation_id, FeedEventKind.MOVEMENT_UPDATED)
        db.commit()
        return load_movement(db, root.id)

    def _create_root(self, db: Session, obs: ObservationEvent, result: DirectionResult, created_by_id, note) -> EntryExitLog:
        log = EntryExitLog(
            vehicle_id=self._attributed_vehicle_id(db, obs),
            plate=obs.raw_plate,
            normalized_plate=obs.normalized_plate or None,
            gate_id=obs.gate_id,
            direction=GateDirection(result.direction.value),
            timestamp=obs.observed_at,
            confidence=obs.plate_confidence,
            decision=None,
            reason_code=None,
            frigate_event_id=obs.source_event_id if obs.source == ObservationSource.FRIGATE else None,
            observation_id=obs.id,
            direction_method=result.method,
            direction_confidence=result.confidence,
            direction_evidence=result.evidence,
            plate_source=LogPlateSource.OBSERVATION,
            created_by_id=created_by_id,
            note=note,
        )
        db.add(log)
        db.flush()
        return log

    @staticmethod
    def _correction_from(eff: EntryExitLog, root: EntryExitLog, **overrides) -> EntryExitLog:
        values = dict(
            vehicle_id=eff.vehicle_id, plate=eff.plate, normalized_plate=eff.normalized_plate,
            gate_id=root.gate_id, direction=eff.direction, timestamp=root.timestamp,
            confidence=eff.confidence, decision=None, reason_code=None,
            frigate_event_id=root.frigate_event_id, observation_id=None, correction_of_id=root.id,
            direction_method=eff.direction_method, direction_confidence=eff.direction_confidence,
            direction_evidence=eff.direction_evidence, plate_source=eff.plate_source,
            created_by_id=None, note=None,
        )
        values.update(overrides)
        return EntryExitLog(**values)

    def _sensor_refinement(self, db: Session, root: EntryExitLog, obs: ObservationEvent) -> None:
        """The camera refined the plate of a logged observation: append a correction, unless a guard corrected it."""
        movement = load_movements(db, [root])[0]
        if movement.has_guard_plate:
            return  # a guard's plate wins over later sensor refinements
        eff = movement.effective
        if not obs.normalized_plate or obs.normalized_plate == eff.normalized_plate:
            return
        db.add(self._correction_from(
            eff, root,
            plate=obs.raw_plate, normalized_plate=obs.normalized_plate, confidence=obs.plate_confidence,
            plate_source=LogPlateSource.OBSERVATION, vehicle_id=self._attributed_vehicle_id(db, obs),
            note="Sensor refinement: the camera updated the plate read.",
        ))
        db.flush()

    @staticmethod
    def _attributed_vehicle_id(db: Session, obs: ObservationEvent) -> Optional[UUID]:
        resolved = identity_resolution_service.resolve_many(db, [obs], with_suggestions=False, with_movement=False)[0]
        return resolved.vehicle.id if resolved.vehicle else None

    @staticmethod
    def _repeat_of_recent(db: Session, obs: ObservationEvent, direction: str) -> bool:
        """Same plate, gate and direction within MOVEMENT_DEBOUNCE_SECONDS of an existing movement."""
        if not obs.normalized_plate:
            return False  # without a plate two detections cannot be shown to be the same vehicle
        window = timedelta(seconds=MOVEMENT_DEBOUNCE_SECONDS)
        roots = (
            movement_roots(db)
            .filter(
                EntryExitLog.gate_id == obs.gate_id,
                EntryExitLog.timestamp >= obs.observed_at - window,
                EntryExitLog.timestamp <= obs.observed_at + window,
            )
            .all()
        )
        return any(
            m.normalized_plate == obs.normalized_plate and m.direction == direction
            for m in load_movements(db, roots)
        )

    # ------------------------------------------------------------------ read side

    def _attribute(self, db: Session, movements: Sequence[Movement]) -> Dict[UUID, _Attribution]:
        out: Dict[UUID, _Attribution] = {}
        guard = [m for m in movements if m.effective.plate_source == LogPlateSource.GUARD_CORRECTION]
        sensor = [m for m in movements if m.effective.plate_source != LogPlateSource.GUARD_CORRECTION]

        vehicles = {
            v.normalized_plate: v
            for v in identity_resolution_service.load_vehicles(db, plates={m.normalized_plate for m in guard if m.normalized_plate})
        }
        for m in guard:
            vehicle = vehicles.get(m.normalized_plate)
            if vehicle is None:
                out[m.id] = _Attribution()
                continue
            linked, owner, residence, _ = identity_resolution_service.vehicle_context(vehicle)
            out[m.id] = _Attribution(linked, owner, residence, "GUARD_PLATE")

        obs_ids = [m.observation_id for m in sensor if m.observation_id]
        observations = (
            db.query(ObservationEvent).options(selectinload(ObservationEvent.gate))
            .filter(ObservationEvent.id.in_(obs_ids)).all()
            if obs_ids else []
        )
        resolved = {
            r.observation.id: r
            for r in identity_resolution_service.resolve_many(db, observations, with_suggestions=False, with_movement=False)
        }
        for m in sensor:
            r = resolved.get(m.observation_id)
            if r is not None and r.vehicle is not None:
                out[m.id] = _Attribution(r.vehicle, r.owner, r.residence, r.link_basis.value if r.link_basis else None)
            else:
                out[m.id] = _Attribution(low_confidence=r is not None and r.link_status == LinkStatus.LOW_CONFIDENCE)
        return out

    def _index(self, db: Session) -> List[_Row]:
        """Every Phase 6 movement with attribution, subject key and sequence flags."""
        movements = load_movements(db, movement_roots(db).all())
        attributions = self._attribute(db, movements)
        rows = []
        for m in movements:
            attr = attributions[m.id]
            if attr.vehicle is not None:
                subject = f"vehicle:{attr.vehicle.id}"
            elif m.normalized_plate:
                subject = f"plate:{m.normalized_plate}"
            else:
                subject = None
            flags = []
            if not m.normalized_plate:
                flags.append("NO_PLATE")
            if attr.low_confidence:
                flags.append("LOW_CONFIDENCE_PLATE")
            if m.corrected:
                flags.append("CORRECTED")
            rows.append(_Row(m, attr, subject, flags))

        for group in self._groups(rows).values():
            previous = None
            for row in group:
                if row.movement.direction == "EXIT" and (previous is None or previous.movement.direction != "ENTRY"):
                    row.flags.append("EXIT_WITHOUT_ENTRY")
                if row.movement.direction == "ENTRY" and previous is not None and previous.movement.direction == "ENTRY":
                    row.flags.append("ENTRY_WHILE_INSIDE")
                previous = row
        return rows

    @staticmethod
    def _groups(rows: Sequence[_Row]) -> Dict[str, List[_Row]]:
        groups: Dict[str, List[_Row]] = defaultdict(list)
        for row in rows:
            if row.subject is not None:
                groups[row.subject].append(row)
        for group in groups.values():
            group.sort(key=lambda r: r.sort_key)
        return groups

    @staticmethod
    def _entry(row: _Row) -> MovementEntry:
        m, attr = row.movement, row.attribution
        eff = m.effective
        return MovementEntry(
            id=m.id,
            observation_id=m.observation_id,
            gate=GateSummary(id=m.gate_id, name=m.root.gate.name if m.root.gate else m.gate_id),
            timestamp=m.timestamp,
            direction=m.direction,
            direction_method=eff.direction_method,
            direction_confidence=eff.direction_confidence,
            plate=eff.plate,
            normalized_plate=eff.normalized_plate,
            plate_source=eff.plate_source,
            linked=attr.vehicle is not None,
            link_basis=attr.basis,
            vehicle=attr.vehicle,
            owner=attr.owner,
            residence=attr.residence,
            flags=list(row.flags),
            corrected=m.corrected,
            correction_count=len(m.rows) - 1,
            recorded_by=_user(m.root.created_by),
            last_corrected_by=_user(eff.created_by) if m.corrected else None,
            note=eff.note,
        )

    def _presence(self, subject: str, group: List[_Row], now: datetime) -> PresenceEntry:
        last = group[-1]
        status = PresenceStatus.INSIDE if last.movement.direction == "ENTRY" else PresenceStatus.OUTSIDE
        flags = [f for f in ("EXIT_WITHOUT_ENTRY", "ENTRY_WHILE_INSIDE") if f in last.flags]
        if status == PresenceStatus.INSIDE and now - last.movement.timestamp > timedelta(hours=PRESENCE_LONG_STAY_HOURS):
            flags.append("LONG_STAY")
        attr = last.attribution
        return PresenceEntry(
            subject=subject,
            status=status,
            normalized_plate=attr.vehicle.plate if attr.vehicle else last.movement.normalized_plate,
            linked=attr.vehicle is not None,
            vehicle=attr.vehicle,
            owner=attr.owner,
            residence=attr.residence,
            last_movement=self._entry(last),
            inside_since=last.movement.timestamp if status == PresenceStatus.INSIDE else None,
            flags=flags,
        )

    def _all_presence(self, db: Session) -> List[PresenceEntry]:
        now = datetime.now(timezone.utc)
        groups = self._groups(self._index(db))
        entries = [self._presence(subject, group, now) for subject, group in groups.items()]
        seen = {s.split(":", 1)[1] for s in groups if s.startswith("vehicle:")}
        for vehicle in db.query(Vehicle).options(selectinload(Vehicle.owner), selectinload(Vehicle.visitor)).all():
            if str(vehicle.id) in seen:
                continue
            linked, owner, residence, _ = identity_resolution_service.vehicle_context(vehicle)
            entries.append(PresenceEntry(
                subject=f"vehicle:{vehicle.id}", status=PresenceStatus.UNKNOWN, normalized_plate=vehicle.normalized_plate,
                linked=True, vehicle=linked, owner=owner, residence=residence,
            ))
        return entries

    def presence(self, db: Session, status: Optional[PresenceStatus] = None, linked: Optional[bool] = None,
                 q: Optional[str] = None, skip: int = 0, limit: int = 100) -> PresencePage:
        entries = self._all_presence(db)
        if status is not None:
            entries = [e for e in entries if e.status == status]
        if linked is not None:
            entries = [e for e in entries if e.linked == linked]
        if q:
            needle_plate = normalize_plate(q)
            needle = q.strip().lower()
            entries = [
                e for e in entries
                if (needle_plate and e.normalized_plate and needle_plate in e.normalized_plate)
                or (e.owner and needle in e.owner.name.lower())
            ]
        order = {PresenceStatus.INSIDE: 0, PresenceStatus.OUTSIDE: 1, PresenceStatus.UNKNOWN: 2}
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        entries.sort(key=lambda e: (order[e.status], -(e.last_movement.timestamp if e.last_movement else epoch).timestamp(), e.normalized_plate or ""))
        return PresencePage(total=len(entries), skip=skip, limit=limit, items=entries[skip: skip + limit])

    def inside(self, db: Session, linked: Optional[bool] = None) -> InsideResponse:
        rows = self._index(db)
        now = datetime.now(timezone.utc)
        items = [
            self._presence(subject, group, now)
            for subject, group in self._groups(rows).items()
            if group[-1].movement.direction == "ENTRY"
        ]
        if linked is not None:
            items = [e for e in items if e.linked == linked]
        items.sort(key=lambda e: e.inside_since, reverse=True)
        cutoff = now - timedelta(hours=PRESENCE_UNATTRIBUTED_LOOKBACK_HOURS)
        unattributed = sorted(
            (r for r in rows if r.subject is None and r.movement.direction == "ENTRY" and r.movement.timestamp >= cutoff),
            key=lambda r: r.sort_key, reverse=True,
        )
        return InsideResponse(total=len(items), items=items, unattributed_entries=[self._entry(r) for r in unattributed])

    def logs(self, db: Session, plate: Optional[str] = None, gate_id: Optional[str] = None, direction: Optional[str] = None,
             date_from: Optional[datetime] = None, date_to: Optional[datetime] = None, linked: Optional[bool] = None,
             skip: int = 0, limit: int = 50) -> MovementPage:
        rows = self._index(db)
        norm = normalize_plate(plate) if plate else None
        selected = []
        for row in rows:
            m, attr = row.movement, row.attribution
            if norm and norm != m.normalized_plate and not (attr.vehicle and attr.vehicle.plate == norm):
                continue
            if gate_id and m.gate_id != gate_id:
                continue
            if direction and m.direction != direction:
                continue
            if date_from and m.timestamp < date_from:
                continue
            if date_to and m.timestamp > date_to:
                continue
            if linked is not None and (attr.vehicle is not None) != linked:
                continue
            selected.append(row)
        selected.sort(key=lambda r: r.sort_key, reverse=True)
        return MovementPage(total=len(selected), skip=skip, limit=limit, items=[self._entry(r) for r in selected[skip: skip + limit]])

    def detail(self, db: Session, log_id: UUID) -> MovementDetail:
        movement = load_movement(db, log_id)
        if movement is None:
            raise MovementError(404, f"Movement '{log_id}' not found.")
        row = next(r for r in self._index(db) if r.movement.id == movement.id)
        return MovementDetail(
            movement=self._entry(row),
            rows=[
                MovementLogRow(
                    id=r.id, correction_of_id=r.correction_of_id, direction=r.direction.value,
                    direction_method=r.direction_method, direction_confidence=r.direction_confidence,
                    direction_evidence=r.direction_evidence or {}, plate=r.plate, normalized_plate=r.normalized_plate,
                    plate_source=r.plate_source, plate_confidence=r.confidence, recorded_vehicle_id=r.vehicle_id,
                    created_by=_user(r.created_by), created_at=r.created_at, note=r.note,
                )
                for r in movement.rows
            ],
        )

    def history(self, db: Session, plate: str) -> VehicleHistory:
        norm = normalize_plate(plate)
        if not norm:
            raise MovementError(400, "Plate must contain at least one letter or digit.")
        vehicle = (
            db.query(Vehicle).options(selectinload(Vehicle.owner), selectinload(Vehicle.visitor))
            .filter(Vehicle.normalized_plate == norm).first()
        )
        primary = f"vehicle:{vehicle.id}" if vehicle else f"plate:{norm}"
        keys = {primary, f"plate:{norm}"}
        rows = self._index(db)
        groups = self._groups(rows)
        mine = [r for r in rows if r.subject in keys]

        now = datetime.now(timezone.utc)
        if groups.get(primary):
            presence = self._presence(primary, groups[primary], now)
        else:
            presence = PresenceEntry(subject=primary, status=PresenceStatus.UNKNOWN, normalized_plate=norm, linked=vehicle is not None)

        logged_obs = {r.movement.observation_id for r in rows if r.movement.observation_id}
        sighting_filter = ObservationEvent.normalized_plate == norm
        if vehicle is not None:
            confirmed = db.query(ObservationResolution.observation_id).filter(ObservationResolution.chosen_vehicle_id == vehicle.id)
            sighting_filter = sighting_filter | ObservationEvent.id.in_(confirmed)
        observations = [
            o for o in (
                db.query(ObservationEvent)
                .options(selectinload(ObservationEvent.gate), selectinload(ObservationEvent.created_by))
                .filter(sighting_filter).order_by(ObservationEvent.observed_at.desc()).limit(500).all()
            )
            if o.id not in logged_obs
        ]
        sightings = identity_resolution_service.resolve_many(db, observations, with_suggestions=False)
        if vehicle is not None:
            # A read of another plate belongs here only while its latest guard resolution names this vehicle.
            sightings = [
                s for s in sightings
                if s.observation.plate.normalized == norm
                or (s.resolution is not None and s.resolution.chosen_vehicle_id == vehicle.id)
            ]

        timeline = [TimelineItem(type="MOVEMENT", time=r.movement.timestamp, gate=self._entry(r).gate, movement=self._entry(r)) for r in mine]
        timeline += [TimelineItem(type="SIGHTING", time=s.observation.observed_at, gate=s.observation.gate, sighting=s) for s in sightings]
        timeline.sort(key=lambda t: t.time, reverse=True)

        linked = owner = residence = None
        link_events = []
        if vehicle is not None:
            linked, owner, residence, _ = identity_resolution_service.vehicle_context(vehicle)
            events = (
                db.query(VehicleLinkEvent).options(selectinload(VehicleLinkEvent.linked_by))
                .filter(VehicleLinkEvent.vehicle_id == vehicle.id).order_by(VehicleLinkEvent.linked_at.asc()).all()
            )
            link_events = [link_event_response(e) for e in events]
        return VehicleHistory(
            plate=plate, normalized_plate=norm, registered=vehicle is not None, vehicle=linked, owner=owner,
            residence=residence, presence=presence, timeline=timeline, link_events=link_events,
        )

    def count_for_plate(self, db: Session, normalized_plate: str) -> Dict[str, int]:
        """How many movements / unlogged sightings of a plate exist (for retroactive-link reporting)."""
        rows = self._index(db)
        logged_obs = {r.movement.observation_id for r in rows if r.movement.observation_id}
        movements = sum(
            1 for r in rows
            if r.movement.normalized_plate == normalized_plate
            or (r.attribution.vehicle is not None and r.attribution.vehicle.plate == normalized_plate)
        )
        sightings = sum(
            1 for (oid,) in db.query(ObservationEvent.id).filter(ObservationEvent.normalized_plate == normalized_plate).all()
            if oid not in logged_obs
        )
        return {"movements": movements, "sightings": sightings}

def link_event_response(event: VehicleLinkEvent) -> LinkEventResponse:
    return LinkEventResponse(
        id=event.id, vehicle_id=event.vehicle_id, owner_id=event.owner_id, method=event.method,
        evidence_note=event.evidence_note, linked_by=_user(event.linked_by), linked_at=event.linked_at,
        expires_at=event.expires_at,
    )

movement_service = MovementService()
