"""
Finding: the unauthenticated GET /health/db (and /health/all) called Base.metadata.create_all().
On an empty database one health probe created every table outside Alembic - without the
append-only triggers - after which `alembic upgrade head` fails on the existing tables, leaving a
schema whose "append-only" tables accept UPDATE and DELETE.
"""
import os

from scripts.audit_regressions.common import PYTHON, VENV_BIN, fresh_schema, run_tool, tables_in

ALEMBIC = os.path.join(VENV_BIN, "alembic")
PROBE = "from backend.app.db import check_db_connection; print(check_db_connection())"


def health_probe_does_not_create_tables():
    with fresh_schema() as (schema, url):
        probe = run_tool([PYTHON, "-c", PROBE], url)
        assert probe.returncode == 0 and "'status': 'ok'" in probe.stdout, f"probe failed: {probe.stdout}{probe.stderr[-500:]}"
        created = tables_in(schema)
        upgrade = run_tool([ALEMBIC, "upgrade", "head"], url)
        assert not created, (
            f"a health probe created {len(created)} tables outside Alembic (e.g. {sorted(created)[:4]}); "
            f"alembic upgrade head then exited {upgrade.returncode}"
        )
        assert upgrade.returncode == 0, upgrade.stderr[-800:]


SCENARIOS = [
    ("health_probe_does_not_create_tables", health_probe_does_not_create_tables),
]
