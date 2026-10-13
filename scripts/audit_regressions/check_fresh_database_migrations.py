"""
Migrations must build a working, drift-free schema from an empty database, not only upgrade the
development database incrementally (where earlier revisions were committed long ago).
"""
import os

from scripts.audit_regressions.common import VENV_BIN, fresh_schema, run_tool, tables_in

ALEMBIC = os.path.join(VENV_BIN, "alembic")


def upgrade_head_succeeds_on_empty_database():
    # Regression from audit commit b49f855: its index predicate used the enum value 'INACTIVE' in the
    # same transaction that added it (all revisions run in one transaction on a fresh database).
    with fresh_schema() as (schema, url):
        upgrade = run_tool([ALEMBIC, "upgrade", "head"], url)
        assert upgrade.returncode == 0, f"alembic upgrade head failed on an empty database:\n{upgrade.stderr[-1200:]}"
        assert "gates" in tables_in(schema)


SCENARIOS = [
    ("upgrade_head_succeeds_on_empty_database", upgrade_head_succeeds_on_empty_database),
]
