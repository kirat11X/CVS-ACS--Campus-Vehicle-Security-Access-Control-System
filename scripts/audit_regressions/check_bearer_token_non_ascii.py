"""
Finding: a bearer token containing a non-ASCII character (HTTP headers are latin-1, so 'é' arrives
intact) made decode_access_token raise UnicodeEncodeError/TypeError inside the auth dependency:
the API answered 500 instead of 401 on every protected endpoint.
"""
from scripts.audit_regressions.common import client


def non_ascii_token_is_unauthorized_not_500():
    for token in ("é.x", "abc.é", "é"):
        resp = client().get("/auth/me", headers={"Authorization": f"Bearer {token}".encode("latin-1")})
        assert resp.status_code == 401, f"token {token!r} -> {resp.status_code} (expected 401)"


SCENARIOS = [
    ("non_ascii_token_is_unauthorized_not_500", non_ascii_token_is_unauthorized_not_500),
]
