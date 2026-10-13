"""Audit 2026-10-13: a failed Roboflow fetch must not print the API key.

fetch_roboflow() sends the key as ?api_key=. requests' HTTPError ("404 Client Error: Not Found for url:
https://api.roboflow.com/...?api_key=...") and ConnectionError messages include that URL, and cmd_fetch
prints every failure, so any failed fetch wrote the key to the terminal and any captured log.
"""
import sys
from argparse import Namespace
from pathlib import Path

import pytest

requests = pytest.importorskip("requests")

TRACK_A = Path(__file__).resolve().parents[2] / "finetune" / "track_a"
sys.path.insert(0, str(TRACK_A))
import fetch_plate_datasets as fetch  # noqa: E402

KEY = "rf-audit-key-must-not-leak-1234"


@pytest.mark.parametrize("failure", ["http_error", "connection_error"])
def test_failed_fetch_does_not_print_the_key(monkeypatch, capsys, failure):
    monkeypatch.setenv("ROBOFLOW_API_KEY", KEY)
    monkeypatch.setattr(fetch, "campus_bytes", lambda: 0)

    def fake_get(url, params=None, timeout=None):
        full_url = f"{url}?api_key={params['api_key']}"
        if failure == "connection_error":
            raise requests.ConnectionError(f"HTTPSConnectionPool(host='api.roboflow.com', port=443): "
                                           f"Max retries exceeded with url: {full_url}")
        response = requests.Response()
        response.status_code, response.url, response.reason = 404, full_url, "Not Found"
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    fetch.cmd_fetch(Namespace(sources=["rf:someone/missing-project"]))
    printed = capsys.readouterr()
    assert KEY not in printed.out + printed.err, "the Roboflow API key was printed"
    assert "FAILED" in printed.out, "the failure itself must still be reported"
