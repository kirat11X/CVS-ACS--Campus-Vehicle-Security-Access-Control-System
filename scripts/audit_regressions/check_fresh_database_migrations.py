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


def upgrade_head_then_check_is_clean_on_empty_database():
    # No revision created health_checks (HealthCheckRecord is in Base.metadata); databases only had it
    # because GET /health/db ran Base.metadata.create_all().
    with fresh_schema() as (schema, url):
        upgrade = run_tool([ALEMBIC, "upgrade", "head"], url)
        assert upgrade.returncode == 0, f"alembic upgrade head failed:\n{upgrade.stderr[-1200:]}"
        check = run_tool([ALEMBIC, "check"], url)
        assert check.returncode == 0, f"alembic check after upgrade head on an empty database:\n{check.stderr[-800:]}"
        assert "health_checks" in tables_in(schema)


SCENARIOS = [
    ("upgrade_head_succeeds_on_empty_database", upgrade_head_succeeds_on_empty_database),
    ("upgrade_head_then_check_is_clean_on_empty_database", upgrade_head_then_check_is_clean_on_empty_database),
]
