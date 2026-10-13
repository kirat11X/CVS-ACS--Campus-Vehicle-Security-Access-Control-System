from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from uuid import UUID
from sqlalchemy.orm import Query, Session, selectinload

from backend.app.models.enums import LogPlateSource
from backend.app.models.gate import EntryExitLog
from backend.app.schemas.feed import MovementSummary, UserSummary

@dataclass
class Movement:
    """A movement = root log row + its correction rows; the latest row is effective."""
    root: EntryExitLog
    rows: List[EntryExitLog]

    @property
    def id(self) -> UUID:
        return self.root.id

    @property
    def effective(self) -> EntryExitLog:
        return self.rows[-1]

    @property
    def direction(self) -> str:
        return self.effective.direction.value

    @property
    def normalized_plate(self) -> Optional[str]:
        return self.effective.normalized_plate

    @property
    def timestamp(self):
        return self.root.timestamp

    @property
    def gate_id(self) -> str:
        return self.root.gate_id

    @property
    def observation_id(self) -> Optional[UUID]:
        return self.root.observation_id

    @property
    def corrected(self) -> bool:
        return len(self.rows) > 1

    @property
    def has_guard_plate(self) -> bool:
        return any(r.plate_source == LogPlateSource.GUARD_CORRECTION for r in self.rows)

def movement_roots(db: Session) -> Query:
    """Root rows of Phase 6 movement records (legacy pre-Phase-6 rows have no direction_method)."""
    return (
        db.query(EntryExitLog)
        .options(selectinload(EntryExitLog.created_by), selectinload(EntryExitLog.gate))
        .filter(EntryExitLog.direction_method.isnot(None), EntryExitLog.correction_of_id.is_(None))
    )

def load_movements(db: Session, roots: Iterable[EntryExitLog]) -> List[Movement]:
    roots = list(roots)
    if not roots:
        return []
    corrections = (
        db.query(EntryExitLog)
        .options(selectinload(EntryExitLog.created_by))
        .filter(EntryExitLog.correction_of_id.in_([r.id for r in roots]))
        .order_by(EntryExitLog.created_at.asc())
        .all()
    )
    by_root: Dict[UUID, List[EntryExitLog]] = defaultdict(list)
    for row in corrections:
        by_root[row.correction_of_id].append(row)
    return [Movement(root=r, rows=[r, *by_root.get(r.id, [])]) for r in roots]

def load_movement(db: Session, log_id: UUID) -> Optional[Movement]:
    """Movement containing log_id (root or correction id)."""
    row = db.get(EntryExitLog, log_id)
    if row is None or row.direction_method is None:
        return None
    root = row if row.correction_of_id is None else db.get(EntryExitLog, row.correction_of_id)
    return load_movements(db, [root])[0]

def movements_for_observations(db: Session, obs_ids: Iterable[UUID]) -> Dict[UUID, Movement]:
    ids = list(obs_ids)
    if not ids:
        return {}
    roots = movement_roots(db).filter(EntryExitLog.observation_id.in_(ids)).all()
    return {m.observation_id: m for m in load_movements(db, roots)}

def _user(user) -> Optional[UserSummary]:
    if user is None:
        return None
    return UserSummary(id=user.id, username=user.username, full_name=user.full_name, role=user.role)

def movement_summary(m: Movement) -> MovementSummary:
    eff = m.effective
    return MovementSummary(
        id=m.id,
        direction=m.direction,
        method=eff.direction_method,
        timestamp=m.timestamp,
        normalized_plate=eff.normalized_plate,
        corrected=m.corrected,
        created_by=_user(eff.created_by),
        note=eff.note,
    )
