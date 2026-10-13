"""
Finding: the ORM guard that keeps movement rows append-only checked the row's *new*
direction_method. Setting direction_method to None in the same change made the guard treat the row
as a legacy (mutable) log and let the UPDATE through to the database; only the trigger stopped it.
"""
import uuid

from backend.app.db import SessionLocal
from backend.app.models import EntryExitLog
from backend.app.models.enums import DirectionMethod, GateDirection
from scripts.audit_regressions.common import ensure_gates


def clearing_direction_method_is_still_rejected_by_orm():
    ensure_gates()
    with SessionLocal() as db:
        row = EntryExitLog(gate_id="GATE_1", direction=GateDirection.ENTRY, plate="PB10AA1111",
                           normalized_plate="PB10AA1111", direction_method=DirectionMethod.GUARD_CONFIRMED,
                           note=f"audit {uuid.uuid4().hex[:6]}")
        db.add(row)
        db.commit()
        row.direction_method = None
        row.direction = GateDirection.EXIT
        try:
            db.flush()
            raised = None
        except Exception as exc:  # noqa: BLE001 - which layer rejected it is the point of the check
            raised = exc
        finally:
            db.rollback()
    assert isinstance(raised, ValueError), (
        f"ORM guard let the movement UPDATE reach the database (rejected by: {type(raised).__name__ if raised else 'nothing'})"
    )


SCENARIOS = [
    ("clearing_direction_method_is_still_rejected_by_orm", clearing_direction_method_is_still_rejected_by_orm),
]
