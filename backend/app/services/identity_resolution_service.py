from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID
from sqlalchemy.orm import Session, selectinload

from backend.app.config import (
    RESOLUTION_CONFIDENCE_THRESHOLD,
    RESOLUTION_SUGGESTION_MIN_SIMILARITY,
    RESOLUTION_SUGGESTION_LIMIT,
)
from backend.app.models.enums import (
    ObservationSource,
    ResolutionOutcome,
    FeedEventKind,
    LinkStatus,
    LinkBasis,
)
from backend.app.models.identity import VehicleOwner, Visitor
from backend.app.models.observation import ObservationEvent, ObservationResolution
from backend.app.models.vehicle import Vehicle
from backend.app.schemas.feed import (
    DirectionInfo,
    FeedObservation,
    LinkedVehicle,
    RegistrySuggestion,
    ResidenceInfo,
    ResolutionSummary,
    ResolvedObservation,
    UserSummary,
)
from backend.app.schemas.observation import GateSummary, PlateObservation, VehicleTypeObservation
from backend.app.schemas.vehicle import OwnerContextResponse
from backend.app.services.direction_resolver import direction_resolver
from backend.app.services.feed_events import record_feed_event
from backend.app.services.movement_lookup import Movement, movement_summary, movements_for_observations
from backend.app.services.plate_similarity import plate_similarity
from backend.app.services.vehicle_identity_service import vehicle_identity_service

@dataclass(frozen=True)
class _Candidate:
    vehicle_id: UUID
    plate: str
    raw_plate: str
    category: str
    registry_status: str
    owner_name: Optional[str]

def _user_summary(user) -> Optional[UserSummary]:
    if user is None:
        return None
    return UserSummary(id=user.id, username=user.username, full_name=user.full_name, role=user.role)

class IdentityResolutionService:
    """
    Phase 5C: associates observations with the vehicle registry for display.

    Read-only with respect to the registry: it never creates Vehicle or VehicleOwner
    rows, never auto-applies a fuzzy candidate, and never produces a threat label or
    an access decision. Registry status is reported exactly as recorded; a link is
    only established by an exact normalized-plate match on a confident read, or by
    a guard's recorded confirmation.
    """

    def __init__(
        self,
        confidence_threshold: float = RESOLUTION_CONFIDENCE_THRESHOLD,
        suggestion_min_similarity: float = RESOLUTION_SUGGESTION_MIN_SIMILARITY,
        suggestion_limit: int = RESOLUTION_SUGGESTION_LIMIT,
    ):
        self.confidence_threshold = confidence_threshold
        self.suggestion_min_similarity = suggestion_min_similarity
        self.suggestion_limit = suggestion_limit

    def is_low_confidence(self, obs: ObservationEvent) -> bool:
        if not obs.normalized_plate:
            return False
        if obs.source == ObservationSource.MANUAL:
            return False  # typed by a guard, not an OCR read
        if obs.plate_confidence is None:
            return True  # OCR output without a score is not assumed correct
        return obs.plate_confidence < self.confidence_threshold

    def resolve(self, db: Session, obs: ObservationEvent) -> ResolvedObservation:
        return self.resolve_many(db, [obs])[0]

    def resolve_many(
        self,
        db: Session,
        observations: Sequence[ObservationEvent],
        with_suggestions: bool = True,
        with_movement: bool = True,
    ) -> List[ResolvedObservation]:
        if not observations:
            return []

        latest = self._latest_resolutions(db, [o.id for o in observations])

        exact_plates = {
            o.normalized_plate for o in observations
            if o.normalized_plate and not self.is_low_confidence(o)
        }
        chosen_ids = {r.chosen_vehicle_id for r in latest.values() if r.chosen_vehicle_id}
        vehicles_by_plate = {v.normalized_plate: v for v in self.load_vehicles(db, plates=exact_plates)}
        vehicles_by_id = {v.id: v for v in self.load_vehicles(db, ids=chosen_ids)}

        movements: Dict[UUID, Movement] = {}
        lanes = {}
        if with_movement:
            movements = movements_for_observations(db, [o.id for o in observations])
            lanes = direction_resolver.load_lanes(db, [o.camera_id for o in observations if o.id not in movements])

        candidates: Optional[List[_Candidate]] = None
        results = []
        for obs in observations:
            low = self.is_low_confidence(obs)
            suggestions: List[RegistrySuggestion] = []
            if low and with_suggestions:
                if candidates is None:
                    candidates = self._registry_candidates(db)
                suggestions = self.suggest(obs.normalized_plate, candidates)

            resolution = latest.get(obs.id)
            vehicle: Optional[Vehicle] = None
            basis: Optional[LinkBasis] = None
            if resolution is not None:
                if resolution.outcome == ResolutionOutcome.VEHICLE_CONFIRMED:
                    vehicle = vehicles_by_id.get(resolution.chosen_vehicle_id)
                    basis = LinkBasis.GUARD_CONFIRMED
                    status = None  # derived from the vehicle below
                else:
                    status = LinkStatus.NOT_LINKED if obs.normalized_plate else LinkStatus.NO_PLATE
            elif not obs.normalized_plate:
                status = LinkStatus.NO_PLATE
            elif low:
                status = LinkStatus.LOW_CONFIDENCE
            else:
                vehicle = vehicles_by_plate.get(obs.normalized_plate)
                basis = LinkBasis.EXACT_PLATE if vehicle else None
                status = None if vehicle else LinkStatus.NOT_LINKED

            item = self._build(obs, status, basis, vehicle, suggestions, resolution, low)
            if with_movement:
                self._attach_movement(db, item, obs, movements.get(obs.id), lanes)
            results.append(item)
        return results

    @staticmethod
    def _attach_movement(db: Session, item: ResolvedObservation, obs: ObservationEvent, movement: Optional[Movement], lanes) -> None:
        if movement is not None:
            eff = movement.effective
            item.movement = movement_summary(movement)
            item.movement_status = "LOGGED"
            item.direction = DirectionInfo(
                direction=movement.direction,
                method=eff.direction_method,
                confidence=eff.direction_confidence,
                evidence=eff.direction_evidence or {},
            )
            return
        result = direction_resolver.resolve(db, obs, lanes)
        item.direction = DirectionInfo(**result.as_dict())
        # A known direction without a log only happens when it repeated a recent movement
        item.movement_status = "REPEAT_NOT_LOGGED" if result.is_known else "DIRECTION_UNKNOWN"

    @staticmethod
    def vehicle_context(vehicle: Vehicle) -> Tuple[LinkedVehicle, Optional[OwnerContextResponse], Optional[ResidenceInfo], List[str]]:
        """Registry context for a loaded vehicle: (vehicle, owner, residence, validity flags)."""
        ctx = vehicle_identity_service.build_context(vehicle)
        v = ctx["vehicle"]
        linked = LinkedVehicle(
            id=v["id"], plate=v["plate"], raw_plate=v["raw_plate"], category=v["category"],
            registry_status=v["status"], is_active=v["is_active"], make_model=v["make_model"],
            color=v["color"], valid_from=v["valid_from"], valid_until=v["valid_until"],
        )
        owner = residence = None
        if ctx["owner"]:
            owner = OwnerContextResponse(**ctx["owner"])
            c = ctx["context"]
            residence = ResidenceInfo(
                person_type=c["person_type"], residence_type=c["residence_type"],
                residence=c["residence"], department=c["department"],
            )
        flags = []
        now = datetime.now(timezone.utc)
        if vehicle.valid_from and now < vehicle.valid_from:
            flags.append("VALIDITY_NOT_STARTED")
        if vehicle.valid_until and now > vehicle.valid_until:
            flags.append("VALIDITY_ENDED")
        return linked, owner, residence, flags

    def suggest(self, plate: str, candidates: Sequence[_Candidate]) -> List[RegistrySuggestion]:
        """Scores registry plates against a low-confidence read; best first."""
        if not plate:
            return []
        scored = []
        for cand in candidates:
            longest = max(len(plate), len(cand.plate))
            # A length gap alone already costs that many edits
            if abs(len(plate) - len(cand.plate)) > longest * (1.0 - self.suggestion_min_similarity):
                continue
            sim = plate_similarity(plate, cand.plate)
            if sim >= self.suggestion_min_similarity:
                scored.append((sim, cand))
        scored.sort(key=lambda pair: (-pair[0], pair[1].plate))
        return [
            RegistrySuggestion(
                vehicle_id=cand.vehicle_id,
                plate=cand.plate,
                raw_plate=cand.raw_plate,
                similarity=sim,
                category=cand.category,
                registry_status=cand.registry_status,
                owner_name=cand.owner_name,
            )
            for sim, cand in scored[: self.suggestion_limit]
        ]

    def record_resolution(
        self,
        db: Session,
        observation: ObservationEvent,
        chosen_vehicle: Optional[Vehicle],
        note: Optional[str],
        user_id: UUID,
    ) -> ObservationResolution:
        """Appends a guard confirmation. The observation row itself is not touched."""
        resolution = ObservationResolution(
            observation_id=observation.id,
            outcome=ResolutionOutcome.VEHICLE_CONFIRMED if chosen_vehicle else ResolutionOutcome.NONE_OF_THESE,
            chosen_vehicle_id=chosen_vehicle.id if chosen_vehicle else None,
            note=note,
            created_by_id=user_id,
        )
        db.add(resolution)
        db.flush()
        record_feed_event(db, observation.id, FeedEventKind.RESOLUTION_ADDED)
        db.commit()
        db.refresh(resolution)
        return resolution

    @staticmethod
    def resolution_summary(resolution: ObservationResolution) -> ResolutionSummary:
        return ResolutionSummary(
            id=resolution.id,
            outcome=resolution.outcome,
            chosen_vehicle_id=resolution.chosen_vehicle_id,
            note=resolution.note,
            created_by=_user_summary(resolution.created_by),
            created_at=resolution.created_at,
        )

    @staticmethod
    def _latest_resolutions(db: Session, obs_ids: List[UUID]) -> Dict[UUID, ObservationResolution]:
        rows = (
            db.query(ObservationResolution)
            .options(selectinload(ObservationResolution.created_by))
            .filter(ObservationResolution.observation_id.in_(obs_ids))
            .order_by(ObservationResolution.created_at.asc())
            .all()
        )
        return {r.observation_id: r for r in rows}  # last (most recent) wins

    @staticmethod
    def load_vehicles(db: Session, plates=None, ids=None) -> List[Vehicle]:
        if not plates and not ids:
            return []
        query = db.query(Vehicle).options(selectinload(Vehicle.owner), selectinload(Vehicle.visitor))
        if plates:
            query = query.filter(Vehicle.normalized_plate.in_(plates))
        else:
            query = query.filter(Vehicle.id.in_(ids))
        return query.all()

    @staticmethod
    def _registry_candidates(db: Session) -> List[_Candidate]:
        rows = (
            db.query(
                Vehicle.id, Vehicle.normalized_plate, Vehicle.raw_plate, Vehicle.vehicle_category,
                Vehicle.status, VehicleOwner.full_name, Visitor.visitor_name,
            )
            .outerjoin(VehicleOwner, Vehicle.owner_id == VehicleOwner.id)
            .outerjoin(Visitor, Vehicle.visitor_id == Visitor.id)
            .all()
        )
        return [
            _Candidate(
                vehicle_id=r[0], plate=r[1], raw_plate=r[2], category=r[3].value,
                registry_status=r[4].value, owner_name=r[5] or r[6],
            )
            for r in rows
        ]

    def _build(
        self,
        obs: ObservationEvent,
        status: Optional[LinkStatus],
        basis: Optional[LinkBasis],
        vehicle: Optional[Vehicle],
        suggestions: List[RegistrySuggestion],
        resolution: Optional[ObservationResolution],
        low: bool,
    ) -> ResolvedObservation:
        flags: List[str] = []
        if obs.source == ObservationSource.MANUAL:
            flags.append("MANUAL_ENTRY")
        if low:
            flags.append("LOW_PLATE_CONFIDENCE")

        linked_vehicle = owner = residence = None
        if vehicle is not None:
            linked_vehicle, owner, residence, validity_flags = self.vehicle_context(vehicle)
            status = LinkStatus.LINKED if linked_vehicle.is_active else LinkStatus.LINKED_INACTIVE
            flags.extend(validity_flags)
        elif status is None:
            # A confirmed vehicle that no longer exists cannot happen (FK), but never guess.
            status = LinkStatus.NOT_LINKED
            basis = None

        meta = obs.metadata_payload if isinstance(obs.metadata_payload, dict) else {}
        observation = FeedObservation(
            id=obs.id,
            gate=GateSummary(id=obs.gate_id, name=obs.gate.name if obs.gate else obs.gate_id),
            camera_id=obs.camera_id,
            observed_at=obs.observed_at,
            updated_at=obs.updated_at,
            source=obs.source,
            source_event_id=obs.source_event_id,
            plate=PlateObservation(raw=obs.raw_plate, normalized=obs.normalized_plate, confidence=obs.plate_confidence),
            vehicle_observation=VehicleTypeObservation(type=obs.vehicle_type, confidence=obs.vehicle_confidence),
            direction=obs.direction,
            note=obs.note,
            created_by=_user_summary(obs.created_by),
            update_count=int(meta.get("update_count", 0) or 0),
            has_snapshot=obs.source == ObservationSource.FRIGATE and bool(obs.source_event_id),
        )

        return ResolvedObservation(
            observation=observation,
            link_status=status,
            link_basis=basis,
            vehicle=linked_vehicle,
            owner=owner,
            residence=residence,
            suggestions=suggestions,
            resolution=self.resolution_summary(resolution) if resolution else None,
            flags=flags,
        )

identity_resolution_service = IdentityResolutionService()
