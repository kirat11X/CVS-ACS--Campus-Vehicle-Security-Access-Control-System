"""
Finding: config.py accepted any AUTH_SECRET_KEY, including the `change-me` placeholder shipped in
.env.example. Tokens are HMAC-signed with that key and every staff user can see other users' ids in
feed responses (created_by.id), so with the placeholder anyone could mint an ADMIN token.
"""
from scripts.audit_regressions.common import PYTHON, run_tool
from backend.app.config import DATABASE_URL

IMPORT_CONFIG = "import backend.app.config"


def _start_with(key):
    import os
    env_backup = os.environ.get("AUTH_SECRET_KEY")
    os.environ["AUTH_SECRET_KEY"] = key
    try:
        return run_tool([PYTHON, "-c", IMPORT_CONFIG], DATABASE_URL)
    finally:
        if env_backup is None:
            os.environ.pop("AUTH_SECRET_KEY", None)
        else:
            os.environ["AUTH_SECRET_KEY"] = env_backup


def placeholder_or_short_secret_refuses_to_start():
    accepted = [key for key in ("change-me", "short-key") if _start_with(key).returncode == 0]
    assert not accepted, f"backend config accepted a guessable AUTH_SECRET_KEY: {accepted}"


def strong_secret_still_starts():
    result = _start_with("x" * 48)
    assert result.returncode == 0, result.stderr[-500:]


SCENARIOS = [
    ("placeholder_or_short_secret_refuses_to_start", placeholder_or_short_secret_refuses_to_start),
    ("strong_secret_still_starts", strong_secret_still_starts),
]
