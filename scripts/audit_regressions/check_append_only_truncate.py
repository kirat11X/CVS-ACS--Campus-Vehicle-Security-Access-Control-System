"""
Finding: the append-only guarantees for observation_resolutions, vehicle_link_events and movement
records in entry_exit_logs were row-level BEFORE UPDATE OR DELETE triggers. Row triggers do not fire
for TRUNCATE, so one TRUNCATE statement erased the whole history without any error.
Each attempt below runs in a transaction that is always rolled back, so no data is lost either way.
"""
from sqlalchemy import create_engine, text

from backend.app.config import DATABASE_URL

STATEMENTS = (
    "TRUNCATE observation_resolutions",
    "TRUNCATE vehicle_link_events",
    "TRUNCATE entry_exit_logs CASCADE",
    "TRUNCATE observation_events CASCADE",  # cascades into resolutions and movement records
)


def truncate_is_rejected_on_append_only_tables():
    engine = create_engine(DATABASE_URL)
    allowed = []
    try:
        for statement in STATEMENTS:
            with engine.connect() as conn:
                trans = conn.begin()
                try:
                    conn.execute(text(statement))
                    allowed.append(statement)
                except Exception as exc:  # noqa: BLE001 - the expected outcome is a rejected statement
                    if "append-only" not in str(exc):
                        allowed.append(f"{statement} (failed for another reason: {str(exc).splitlines()[0]})")
                finally:
                    trans.rollback()
    finally:
        engine.dispose()
    assert not allowed, f"append-only history can be erased: {allowed}"


SCENARIOS = [
    ("truncate_is_rejected_on_append_only_tables", truncate_is_rejected_on_append_only_tables),
]
