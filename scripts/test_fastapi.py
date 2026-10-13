import os
import sys
import time
import httpx
import uvicorn
import threading

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def run_server():
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def test_endpoints():
    client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=5.0)

    # 1. Test /health
    print("[TEST] Testing GET /health...")
    r = client.get("/health")
    print(f"  Response ({r.status_code}): {r.json()}")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    # 2. Test /health/db
    print("[TEST] Testing GET /health/db...")
    r = client.get("/health/db")
    print(f"  Response ({r.status_code}): {r.json()}")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

    # 3. Test /health/mqtt
    print("[TEST] Testing GET /health/mqtt...")
    r = client.get("/health/mqtt")
    print(f"  Response ({r.status_code}): {r.json()}")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

    # 4. Test /health/all
    print("[TEST] Testing GET /health/all...")
    r = client.get("/health/all")
    print(f"  Response ({r.status_code}): {r.json()}")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"

    # 5. Test n8n webhook receiver endpoint
    print("[TEST] Testing POST /webhook/n8n-test...")
    payload = {"source": "n8n_test_flow", "event": "invoice_received", "data": {"invoice_id": "ORD-2026-9821"}}
    r = client.post("/webhook/n8n-test", json=payload)
    print(f"  Response ({r.status_code}): {r.json()}")
    assert r.status_code == 200
    assert r.json().get("status") == "success"

    print("\n[FASTAPI ALL HEALTH CHECKS PASSED]")

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(1.5)  # Wait for server to start

    try:
        test_endpoints()
    except Exception as e:
        print(f"FastAPI test failed: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
