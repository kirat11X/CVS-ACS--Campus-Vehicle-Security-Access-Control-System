"""Review-only safety guards: no network or production imports."""

import socket
import sys


_FORBIDDEN_MODULE_PREFIXES = (
    "backend",
    "alembic",
    "sqlalchemy.orm",
    "paho",
)


def _network_disabled(*args, **kwargs):
    raise RuntimeError("Network access is disabled for research-track review tests")


class _NetworkDisabledSocket(socket.socket):
    # A class, not a function: stdlib modules imported later (ssl, via pytest's pdb on 3.14) subclass socket.socket.
    def __init__(self, *args, **kwargs):
        _network_disabled()


socket.socket = _NetworkDisabledSocket  # type: ignore[misc]
socket.create_connection = _network_disabled  # type: ignore[assignment]


def pytest_sessionstart(session):
    imported = sorted(
        name for name in sys.modules
        if name == "backend"
        or name == "alembic"
        or name.startswith(_FORBIDDEN_MODULE_PREFIXES[2:])
        or name.startswith("paho")
    )
    if imported:
        raise AssertionError(f"Forbidden production modules imported: {imported}")
