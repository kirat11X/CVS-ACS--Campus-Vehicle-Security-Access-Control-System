"""
Finding: alembic/env.py passed DATABASE_URL to Config.set_main_option(), which runs it through
configparser interpolation. Any '%' in the URL - i.e. any URL-encoded password character such as
%40 for '@' - made every alembic command fail with "invalid interpolation syntax".
"""
import os

from backend.app.config import DATABASE_URL
from scripts.audit_regressions.common import VENV_BIN, run_tool

ALEMBIC = os.path.join(VENV_BIN, "alembic")


def percent_encoded_password_works():
    # '%5F' is '_' URL-encoded: the same credentials, spelled the way an encoded password would be.
    scheme, rest = DATABASE_URL.split("://", 1)
    userinfo, host = rest.split("@", 1)
    user, password = userinfo.split(":", 1)
    encoded = f"{scheme}://{user}:{password.replace('_', '%5F')}@{host}"
    assert "%" in encoded, "fixture needs a password containing '_'"
    result = run_tool([ALEMBIC, "current"], encoded)
    assert result.returncode == 0, f"alembic with a URL-encoded password failed:\n{result.stderr[-600:]}"


SCENARIOS = [
    ("percent_encoded_password_works", percent_encoded_password_works),
]
