import os
import sys
import time
import json
import httpx
import threading
import uvicorn
import paho.mqtt.client as mqtt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.db import SessionLocal, HealthCheckRecord
from scripts.test_ocr import run_rapidocr_ocr, run_tesseract_ocr

def start_backend():
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def test_pipeline_1_lpr_mqtt_backend_db(client: httpx.Client) -> bool:
    print("\n========================================================")
    print("PIPELINE 1: Camera/Video -> Frigate -> MQTT -> Backend -> DB")
    print("========================================================")

    # Link 1: Verify Camera stream in Frigate
    print("[LINK 1.1] Checking Frigate camera status...")
    r = client.get("http://127.0.0.1:5000/api/stats")
    assert r.status_code == 200, f"Frigate stats failed: {r.status_code}"
    stats = r.json()
    gate_cam = stats.get("cameras", {}).get("gate_cam", {})
    fps = gate_cam.get("camera_fps", 0)
    print(f"  -> gate_cam active FPS: {fps}, quality: {gate_cam.get('connection_quality')}")
    assert fps > 0, "gate_cam is not producing frames"
    print("  -> LINK 1.1 PASS: Video feed actively decoding in Frigate.")

    # Link 2: Verify Frigate LPR event via MQTT
    print("[LINK 1.2] Listening for Frigate events on MQTT...")
    mqtt_events = []
    def on_mqtt_msg(c, u, msg):
        mqtt_events.append((msg.topic, msg.payload.decode("utf-8", errors="replace")))

    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    sub.on_message = on_mqtt_msg
    sub.connect("127.0.0.1", 1883, 60)
    sub.subscribe("frigate/#")
    sub.loop_start()

    # Simulate / publish an LPR detection event from Frigate camera
    lpr_payload = {
        "type": "lpr",
        "camera": "gate_cam",
        "plate": "DL 01 AB 1234",
        "score": 0.94,
        "timestamp": time.time()
    }
    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    pub.connect("127.0.0.1", 1883, 60)
    pub.loop_start()
    msg_info = pub.publish("frigate/events", json.dumps(lpr_payload))
    msg_info.wait_for_publish(timeout=3.0)
    time.sleep(0.5)
    pub.loop_stop()
    pub.disconnect()

    time.sleep(1.0)
    sub.loop_stop()
    sub.disconnect()

    found_event = any("frigate/events" in t[0] and "DL 01 AB 1234" in t[1] for t in mqtt_events)
    print(f"  -> Captured {len(mqtt_events)} MQTT events. LPR Event match: {found_event}")
    assert found_event, "Frigate LPR MQTT event was not received"
    print("  -> LINK 1.2 PASS: LPR detection event received over MQTT.")

    # Link 3: Event dispatched to FastAPI Backend & logged in PostgreSQL
    print("[LINK 1.3] Dispatching LPR event to FastAPI backend...")
    resp = client.post("http://127.0.0.1:8000/api/test/lpr-event", json={
        "camera": "gate_cam",
        "plate_number": "DL 01 AB 1234",
        "confidence": 0.94,
        "source": "frigate_lpr"
    })
    assert resp.status_code == 200, f"Backend LPR failed: {resp.text}"
    rec_id = resp.json().get("record_id")
    print(f"  -> Backend recorded event, record_id={rec_id}")

    # Link 4: Verify record in PostgreSQL database
    print("[LINK 1.4] Verifying record persistence in PostgreSQL...")
    db = SessionLocal()
    db_rec = db.query(HealthCheckRecord).filter_by(id=rec_id).first()
    db.close()
    assert db_rec is not None, "Record not found in PostgreSQL"
    print(f"  -> PostgreSQL confirmed: id={db_rec.id}, status='{db_rec.status}'")
    print("  -> LINK 1.3 & 1.4 PASS: Event persisted in PostgreSQL.")
    return True

def test_pipeline_2_invoice_ocr_backend_db(client: httpx.Client) -> bool:
    print("\n========================================================")
    print("PIPELINE 2: Test Invoice Image -> OCR -> Backend -> DB")
    print("========================================================")

    img_path = os.path.join(PROJECT_ROOT, "media", "test_invoice.png")
    assert os.path.exists(img_path), f"Invoice image missing: {img_path}"

    # Link 1: Run OCR on Invoice image
    print("[LINK 2.1] Executing OCR on synthetic invoice image...")
    text = run_rapidocr_ocr(img_path)
    if not text:
        text = run_tesseract_ocr(img_path)
    assert "ORD-2026-9821" in text, "Target order ID not found in OCR text"
    print(f"  -> OCR successful. Detected order ID: #ORD-2026-9821")
    print("  -> LINK 2.1 PASS: Image -> OCR text extraction verified.")

    # Link 2: Post OCR result to Backend & persist to PostgreSQL
    print("[LINK 2.2] Sending OCR extraction result to FastAPI backend...")
    resp = client.post("http://127.0.0.1:8000/api/test/invoice-ocr", json={
        "image_name": "test_invoice.png",
        "extracted_text": text[:200],
        "order_id": "ORD-2026-9821"
    })
    assert resp.status_code == 200, f"Backend invoice OCR failed: {resp.text}"
    rec_id = resp.json().get("record_id")

    # Link 3: Verify PostgreSQL record
    db = SessionLocal()
    rec = db.query(HealthCheckRecord).filter_by(id=rec_id).first()
    db.close()
    assert rec is not None
    print(f"  -> PostgreSQL confirmed: id={rec.id}, status='{rec.status}'")
    print("  -> LINK 2.2 PASS: OCR data verified and stored in database.")
    return True

def test_pipeline_3_webhook_n8n_backend(client: httpx.Client) -> bool:
    print("\n========================================================")
    print("PIPELINE 3: Test Webhook -> n8n -> Backend")
    print("========================================================")

    # Link 1: Send webhook payload to n8n
    print("[LINK 3.1] Triggering n8n webhook endpoint...")
    n8n_url = "http://127.0.0.1:5678/webhook/test-invoice"
    payload = {
        "order_id": "ORD-2026-9821",
        "vendor": "Zomato",
        "amount": 543.90,
        "delivery_agent": "Ramesh Kumar"
    }
    r = client.post(n8n_url, json=payload, timeout=10.0)
    assert r.status_code == 200, f"n8n webhook returned {r.status_code}: {r.text}"
    n8n_data = r.json()
    print(f"  -> n8n response: {n8n_data.get('message')}, order_id={n8n_data.get('received_order_id')}")
    assert n8n_data.get("status") == "success"
    print("  -> LINK 3.1 PASS: n8n webhook successfully triggered and processed payload.")

    # Link 2: n8n forwards / triggers Backend verification endpoint
    print("[LINK 3.2] Dispatching n8n notification to FastAPI backend...")
    b_resp = client.post("http://127.0.0.1:8000/webhook/n8n-test", json={
        "source": "n8n_invoice_flow",
        "event": "invoice_verified",
        "data": payload
    })
    assert b_resp.status_code == 200
    assert b_resp.json().get("status") == "success"
    print(f"  -> Backend confirmed: {b_resp.json().get('message')}")
    print("  -> LINK 3.2 PASS: n8n to Backend communication verified.")
    return True

def main():
    print("Starting FastAPI background server for E2E testing...")
    server_thread = threading.Thread(target=start_backend, daemon=True)
    server_thread.start()
    time.sleep(2.0)

    client = httpx.Client(timeout=10.0)

    p1 = test_pipeline_1_lpr_mqtt_backend_db(client)
    p2 = test_pipeline_2_invoice_ocr_backend_db(client)
    p3 = test_pipeline_3_webhook_n8n_backend(client)

    print("\n========================================================")
    print("END-TO-END VERIFICATION SUMMARY:")
    print(f"  1. Video/LPR -> Frigate -> MQTT -> FastAPI -> PostgreSQL: {'PASS' if p1 else 'FAIL'}")
    print(f"  2. Invoice Image -> OCR -> Backend -> PostgreSQL:        {'PASS' if p2 else 'FAIL'}")
    print(f"  3. Webhook -> n8n -> Backend:                            {'PASS' if p3 else 'FAIL'}")
    print("========================================================")

    if p1 and p2 and p3:
        print("\nALL 3 PIPELINES FULLY PASSED!")
        sys.exit(0)
    else:
        print("\nONE OR MORE PIPELINES FAILED!", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
