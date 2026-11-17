import base64
import importlib.util
import os
import random
import sys
import tempfile
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path
import httpx
import uvicorn

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import text

from backend.app.config import MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.models import (
    AccessDecision, DeliveryDecision, Gate, PersonType, ResidenceType, ScreeningVerdict, User, Vehicle,
    VehicleCategory, VehicleOwner,
)
from backend.app.services.auth_service import hash_password
from backend.app.services.delivery_policy import REASON_VERDICTS, screen_line, worst
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.services.invoice_reader import parse_item_text, parse_rows, parse_text, read_image, run_tesseract
from backend.app.services.registry_match import classify_plate

BASE_URL = "http://127.0.0.1:8000"
SAFE_LETTERS = "ACEHJKLMNPRTUVWXY"
DEMO_PNG = MEDIA_ROOT / "demo" / "invoice_D-20481.png"
DEMO_PDF = MEDIA_ROOT / "demo" / "invoice_D-20481.pdf"
EXPECTED_VERDICTS = ["ALLOW", "ALLOW", "REVIEW", "ALERT", "ALLOW"]

# OCR text of the slide-8 demo invoice, as the parser receives it (one row per line)
DEMO_TEXT = """DEMO MART
TAX INVOICE · SAMPLE
Order #D-20481  10 Oct 2026
Item  Qty  Amount
Instant noodles 70g  4  56.00
Cola 750 ml  2  80.00
Toilet cleaner 500 ml  1  99.00
Cigarettes pack of 20  1  350.00
Notebook A4 ruled  2  90.00
Subtotal  675.00
Delivery  25.00
TOTAL  700.00
Sample invoice for demonstration · not a real order"""

def start_backend():
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def wait_for_backend(timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Backend did not start")

def _seed_module():
    spec = importlib.util.spec_from_file_location("seed_demo", os.path.join(PROJECT_ROOT, "scripts", "seed_demo.py"))
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    return seed

def ensure_demo_invoice():
    if not (DEMO_PNG.exists() and DEMO_PDF.exists()):
        _seed_module().generate_invoice()  # image only, no database writes

def invoice_for(order_id: str) -> bytes:
    """The demo invoice printed with another order number (written to a temp dir, not media/)."""
    with tempfile.TemporaryDirectory(prefix="p7_") as folder:
        path = Path(folder) / "invoice.png"
        _seed_module().generate_invoice(order_id=order_id, png_path=path, pdf_path=None)
        return path.read_bytes()

def new_plate(prefix="CH17"):
    letters = "".join(random.choice(SAFE_LETTERS) for _ in range(2))
    digits = "".join(random.choice("1345679") for _ in range(4))
    return f"{prefix}{letters}{digits}"

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def run_tests():
    print("========================================================")
    print("PHASE 7: DELIVERY SCREENING, LOCAL INTAKE, ALERTS & WHATSAPP PROVIDER")
    print("========================================================")
    ensure_demo_invoice()
    png = DEMO_PNG.read_bytes()
    tag = uuid.uuid4().hex[:6].upper()

    # --- Scenario 1: Policy table ---
    print("\n[SCENARIO 1] Deterministic policy table: category -> reason code -> verdict...")
    cases = {
        "Instant noodles 70g": ("FOOD", "FOOD_OK", "ALLOW"),
        "Cola 750 ml": ("BEVERAGE", "BEVERAGE_OK", "ALLOW"),
        "Notebook A4 ruled": ("STATIONERY", "STATIONERY_OK", "ALLOW"),
        "Dove soap 100g": ("PERSONAL_CARE", "PERSONAL_CARE_OK", "ALLOW"),
        "USB-C charger 20W": ("ELECTRONICS", "ELECTRONICS_OK", "ALLOW"),
        "Toilet cleaner 500 ml": ("HAZMAT", "HAZMAT_NEEDS_APPROVAL", "REVIEW"),
        "Phenyl 1L": ("HAZMAT", "HAZMAT_NEEDS_APPROVAL", "REVIEW"),
        "Lighter fluid": ("HAZMAT", "HAZMAT_NEEDS_APPROVAL", "REVIEW"),
        "Paracetamol 500mg strip": ("MEDICINE", "MEDICINE_NEEDS_APPROVAL", "REVIEW"),
        "Cigarettes pack of 20": ("TOBACCO", "TOBACCO_RESTRICTED", "ALERT"),
        "Gutka sachet": ("TOBACCO", "TOBACCO_RESTRICTED", "ALERT"),
        "Kingfisher beer 650ml": ("ALCOHOL", "ALCOHOL_RESTRICTED", "ALERT"),
        "Kitchen knife set": ("WEAPON", "WEAPON_RESTRICTED", "ALERT"),
        "Chocolate cigarettes": ("TOBACCO", "TOBACCO_RESTRICTED", "ALERT"),  # most severe category wins
        "Vanilla ice cream": ("FOOD", "FOOD_OK", "ALLOW"),                     # longest keyword wins
        "NotebookA4ruled": ("STATIONERY", "STATIONERY_OK", "ALLOW"),           # OCR dropped the spaces
        "Zxq widget": ("UNKNOWN", "UNKNOWN_CATEGORY", "REVIEW"),               # never silently ALLOW
    }
    for name, (category, reason, verdict) in cases.items():
        s = screen_line(name)
        assert (s.category, s.reason_code, s.verdict.value) == (category, reason, verdict), (name, s)
        assert REASON_VERDICTS[s.reason_code] == s.verdict
    low = screen_line("Cola 750 ml", ocr_confidence=0.3)
    assert (low.reason_code, low.verdict.value, low.category) == ("UNREADABLE_LINE", "REVIEW", "BEVERAGE")
    assert screen_line("Cigarettes", ocr_confidence=0.3).verdict == ScreeningVerdict.ALERT
    assert screen_line("~~##", readable=False).reason_code == "UNREADABLE_LINE"
    assert worst([ScreeningVerdict.ALLOW, ScreeningVerdict.REVIEW]) == ScreeningVerdict.REVIEW
    assert worst([ScreeningVerdict.REVIEW, ScreeningVerdict.ALERT, ScreeningVerdict.ALLOW]) == ScreeningVerdict.ALERT
    print(f"  -> {len(cases)} item names mapped as the contract table says; conflicts resolve to the more severe category")
    print("  -> a low-confidence ALLOW line becomes UNREADABLE_LINE / REVIEW; restricted lines stay ALERT")
    print("  -> PASS Scenario 1")

    # --- Scenario 2: Parser + arithmetic on the demo invoice text ---
    print("\n[SCENARIO 2] Parser and arithmetic check on the slide-8 invoice text...")
    parsed = parse_text(DEMO_TEXT)
    assert [(l.item_name, l.quantity, l.amount) for l in parsed.lines] == [
        ("Instant noodles 70g", 4, Decimal("56.00")), ("Cola 750 ml", 2, Decimal("80.00")),
        ("Toilet cleaner 500 ml", 1, Decimal("99.00")), ("Cigarettes pack of 20", 1, Decimal("350.00")),
        ("Notebook A4 ruled", 2, Decimal("90.00")),
    ], [(l.item_name, l.quantity, l.amount) for l in parsed.lines]
    assert (parsed.vendor, parsed.order_number) == ("DEMO MART", "D-20481"), (parsed.vendor, parsed.order_number)
    assert (parsed.subtotal, parsed.delivery_fee, parsed.total) == (Decimal("675.00"), Decimal("25.00"), Decimal("700.00"))
    result = delivery_screening_service.screen(parsed, "D-20481")
    assert [l.verdict.value for l in result.lines] == EXPECTED_VERDICTS
    assert result.totals_match is True and result.computed_total == Decimal("700.00") and result.overall == ScreeningVerdict.ALERT
    reply = delivery_screening_service.reply_text("D-20481", result)
    assert reply == "Order D-20481: 2 of 5 lines need a look. Total matches: 700.00.", reply

    bad = delivery_screening_service.screen(parse_text(DEMO_TEXT.replace("TOTAL  700.00", "TOTAL  710.00")), "D-20481")
    assert bad.totals_match is False and "does not add up" in delivery_screening_service.reply_text("D-20481", bad)
    fine_text = "SHOP\nItem  Qty  Amount\nCola 750 ml  2  80.00\nNotebook A4  1  45.00\nTOTAL  125.00"
    fine = delivery_screening_service.screen(parse_text(fine_text), "X-1")
    assert fine.overall == ScreeningVerdict.ALLOW and fine.totals_match is True
    no_total = delivery_screening_service.screen(parse_text(fine_text.replace("\nTOTAL  125.00", "")), "X-1")
    assert no_total.totals_match is None and no_total.overall == ScreeningVerdict.REVIEW
    other = delivery_screening_service.screen(parsed, "D-99999")
    assert other.overall == ScreeningVerdict.ALERT and "invoice shows order D-20481" in delivery_screening_service.reply_text("D-99999", other)
    # Column cells as OCR splits them: a number inside the name cell is not the quantity
    assert parse_item_text("Cigarettes pack of 20  350.00") == {"name": "Cigarettes pack of 20", "quantity": None, "unit_price": None, "amount": Decimal("350.00")}
    assert parse_item_text("Cola 750 ml  2  40.00  80.00")["unit_price"] == Decimal("40.00")
    assert parse_item_text("Cola 750 ml 2 80.00")["quantity"] == 2  # single cell: trailing integer before the amount
    garbled = parse_text("Item  Qty  Amount\n### %% 12.50\nCola  1  20.00\nTOTAL  32.50")
    assert [l.readable for l in garbled.lines] == [False, True]
    assert delivery_screening_service.screen(garbled).lines[0].reason_code == "UNREADABLE_LINE"
    print("  -> 5 lines (item, qty, amount), Subtotal 675.00 + Delivery 25.00 = TOTAL 700.00, vendor and order number read")
    print(f"  -> verdicts {','.join(EXPECTED_VERDICTS)}; reply: \"{reply}\"")
    print("  -> total off by 10 -> 'does not add up'; no printed total -> REVIEW; all-allowed matching invoice -> ALLOW")
    print("  -> PASS Scenario 2")

    # --- Scenario 3: OCR on the generated invoice image ---
    print("\n[SCENARIO 3] OCR (RapidOCR primary, Tesseract fallback) on media/demo/invoice_D-20481.png...")
    t0 = time.time()
    ocr = read_image(DEMO_PNG)
    rapid_s = time.time() - t0
    result = delivery_screening_service.screen(parse_rows(ocr.rows), "D-20481")
    assert ocr.engine == "RAPIDOCR", ocr.engine
    assert len(result.lines) == 5, [l.item_name for l in result.lines]
    assert [l.verdict.value for l in result.lines] == EXPECTED_VERDICTS, [(l.item_name, l.verdict.value) for l in result.lines]
    assert result.totals_match is True and result.computed_total == Decimal("700.00")
    assert [l.quantity for l in result.lines] == [4, 2, 1, 1, 2], [(l.item_name, l.quantity) for l in result.lines]
    assert result.lines[3].item_name == "Cigarettes pack of 20"
    tess = run_tesseract(DEMO_PNG)
    tess_result = delivery_screening_service.screen(parse_rows(tess.rows), "D-20481")
    tess_ok = len(tess_result.lines) == 5 and tess_result.totals_match is True
    print(f"  -> RapidOCR: 5 lines, qty 4/2/1/1/2, verdicts {','.join(l.verdict.value for l in result.lines)}, total 700.00 matches ({rapid_s:.1f}s)")
    print(f"  -> Tesseract fallback on the same image: {len(tess_result.lines)} lines, totals_match={tess_result.totals_match}"
          + ("" if tess_ok else "  (fallback weaker than RapidOCR on this image)"))
    print("  -> PASS Scenario 3")

    # --- Scenario 4: Slide-6 registry match ---
    print("\n[SCENARIO 4] Slide-6 plate reading: edit-distance match against the registry...")
    registry = ["CH01AB1234", "CH01AB1247", "CH01AB1248", "HR26DK0042", "PB65XY7788"]
    m = classify_plate("CH01AB11234", registry)
    assert (m.outcome, m.basis, m.plates) == ("LINKED", "ONE_EDIT", ("CH01AB1234",)) and "removing 1 extra character" in m.explanation
    m = classify_plate("HR26DK004Z", registry)
    assert (m.outcome, m.plates) == ("LINKED", ("HR26DK0042",)) and "Z read for 2" in m.explanation, m
    m = classify_plate("CH01AB124", registry)
    assert m.outcome == "NEEDS_REVIEW" and set(m.plates) == {"CH01AB1234", "CH01AB1247", "CH01AB1248"}, m
    m = classify_plate("UP332KL5567", registry)
    assert (m.outcome, m.explanation) == ("UNLINKED", "No registry plate within one edit")
    assert classify_plate("PB65XY7788", registry).basis == "EXACT"
    print("  -> CH01AB11234 LINKED (removed 1 extra character), HR26DK004Z LINKED (Z read for 2)")
    print("  -> CH01AB124 NEEDS REVIEW (3 close plates), UP332KL5567 UNLINKED")
    print("  -> PASS Scenario 4")

    # --- API set-up ---
    client = httpx.Client(base_url=BASE_URL, timeout=60.0)
    db = SessionLocal()
    for gate_id, name, cam in (("GATE_1", "Main North Gate", "gate_cam"), ("GATE_2", "South Gate", "gate_2_cam")):
        if not db.get(Gate, gate_id):
            db.add(Gate(id=gate_id, name=name, camera_id=cam, status="ACTIVE"))
    passwords, users = {}, {}
    for role in ("ADMIN", "GUARD"):
        pw = uuid.uuid4().hex
        u = User(username=f"p7_{role.lower()}_{tag.lower()}", email=f"p7_{role.lower()}_{tag.lower()}@campus.edu",
                 full_name=f"Phase 7 {role.title()}", role=role, hashed_password=hash_password(pw))
        db.add(u)
        users[role], passwords[role] = u, pw
    db.commit()
    for u in users.values():
        db.refresh(u)
    access_decisions_start = db.query(AccessDecision).count()
    db.close()
    tokens = {}
    for role, u in users.items():
        r = client.post("/auth/login", json={"username": u.username, "password": passwords[role]})
        assert r.status_code == 200, r.text
        tokens[role] = r.json()["access_token"]
    guard, admin = tokens["GUARD"], tokens["ADMIN"]

    # --- Scenario 5: WhatsApp provider status ---
    print("\n[SCENARIO 5] GET /system/whatsapp reports the provider, intake URL and outbox...")
    assert client.get("/system/whatsapp").status_code == 401
    status = client.get("/system/whatsapp", headers=auth(guard)).json()
    assert status["provider"] in ("local", "mock", "meta") and status["intake_url"].endswith("/intake"), status
    assert isinstance(status["available"], bool) and isinstance(status["outbox_count"], int)
    print(f"  -> provider={status['provider']} available={status['available']} intake_url={status['intake_url']} outbox={status['outbox_count']}")
    print("  -> PASS Scenario 5")

    # --- Scenario 6: Public LAN intake page and upload ---
    print("\n[SCENARIO 6] GET /intake page and POST /intake/upload (HTML and JSON)...")
    page = client.get("/intake")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    for needle in ("Send delivery invoice", 'name="order_id"', 'name="file"', 'name="sender_phone"', 'name="gate_id"', "GATE_3"):
        assert needle in page.text, needle
    assert "http://" not in page.text.replace("http://www.w3.org", "") and "<link" not in page.text  # no external assets
    flags_before = client.get("/dashboard/summary", headers=auth(guard)).json()["delivery_flags"]
    order_a = f"P7-{tag}A"
    r = client.post("/intake/upload", headers={"Accept": "application/json"},
                    data={"order_id": order_a.lower(), "sender_phone": "+919800000007", "gate_id": "GATE_1"},
                    files={"file": ("invoice.png", png, "image/png")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["order_id"] == order_a and body["reply_text"] == f"Order {order_a}: 2 of 5 lines need a look. Total matches: 700.00. The invoice shows order D-20481.", body["reply_text"]
    assert [i["verdict"] for i in body["items"]] == EXPECTED_VERDICTS and body["overall"] == "ALERT"
    order_b = f"P7-{tag}B"
    html = client.post("/intake/upload", data={"order_id": order_b}, files={"file": ("invoice.png", png, "image/png")})
    assert html.status_code == 201 and "text/html" in html.headers["content-type"] and "need a look" in html.text and "TOBACCO_RESTRICTED" in html.text
    bad = client.post("/intake/upload", headers={"Accept": "application/json"}, data={"order_id": f"P7-{tag}X"},
                      files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 415, bad.text
    assert client.post("/intake/upload", data={"order_id": f"P7-{tag}X"},
                       files={"file": ("x.png", b"not an image", "image/png")}).status_code == 415
    assert client.post("/intake/upload", files={"file": ("invoice.png", png, "image/png")}).status_code == 422
    assert client.post("/intake/upload", headers={"Accept": "application/json"}, data={"order_id": "../etc"},
                       files={"file": ("invoice.png", png, "image/png")}).status_code == 400
    order_pdf = f"P7-{tag}PDF"
    r = client.post("/intake/upload", headers={"Accept": "application/json"}, data={"order_id": order_pdf, "gate_id": "GATE_2"},
                    files={"file": ("invoice.pdf", DEMO_PDF.read_bytes(), "application/pdf")})
    assert r.status_code == 201 and [i["verdict"] for i in r.json()["items"]] == EXPECTED_VERDICTS, r.text
    assert all(i["quantity"] in (None, q) for i, q in zip(r.json()["items"], (4, 2, 1, 1, 2))), r.json()["items"]  # unread qty stays None
    after = client.get("/system/whatsapp", headers=auth(guard)).json()
    if after["provider"] in ("local", "mock"):
        assert after["outbox_count"] >= status["outbox_count"] + 3, (status, after)
    print("  -> mobile page has order ID, phone, gate and file fields, inline CSS only")
    print(f"  -> JSON reply: \"{body['reply_text']}\"")
    print("  -> HTML chat-style result page; junk file 415, missing order ID 422, bad order ID 400")
    print("  -> a PDF invoice is rendered (page 1) and screened the same way")
    print("  -> PASS Scenario 6")

    # --- Scenario 7: List, detail, invoice image ---
    print("\n[SCENARIO 7] GET /deliveries, /deliveries/{order_id}, invoice image (bearer auth)...")
    assert client.get("/deliveries").status_code == 401
    listed = client.get("/deliveries", params={"q": tag}, headers=auth(guard)).json()
    assert {d["order_id"] for d in listed} == {order_a, order_b, order_pdf}, listed
    s = next(d for d in listed if d["order_id"] == order_a)
    assert (s["source"], s["sender"], s["gate_id"], s["line_count"], s["review_count"], s["alert_count"]) == \
        ("LOCAL_INTAKE", "+919800000007", "GATE_1", 5, 1, 1), s
    assert s["overall"] == "ALERT" and s["totals_match"] is True and s["total_amount"] == 700.0 and s["latest_decision"] is None
    assert all(d["overall"] == "ALERT" for d in client.get("/deliveries", params={"q": tag, "verdict": "ALERT"}, headers=auth(guard)).json())
    assert client.get("/deliveries", params={"q": tag, "verdict": "ALLOW"}, headers=auth(guard)).json() == []
    assert {d["order_id"] for d in client.get("/deliveries", params={"q": tag, "status": "pending"}, headers=auth(guard)).json()} == {order_a, order_b, order_pdf}
    d = client.get(f"/deliveries/{order_a}", headers=auth(guard)).json()
    assert [(i["line_no"], i["category_label"], i["reason_code"], i["verdict"]) for i in d["items"]] == [
        (1, "Food", "FOOD_OK", "ALLOW"), (2, "Beverage", "BEVERAGE_OK", "ALLOW"),
        (3, "Hazardous chemical", "HAZMAT_NEEDS_APPROVAL", "REVIEW"), (4, "Tobacco", "TOBACCO_RESTRICTED", "ALERT"),
        (5, "Stationery", "STATIONERY_OK", "ALLOW"),
    ], d["items"]
    inv = d["invoice"]
    assert (inv["subtotal"], inv["delivery_fee"], inv["total"], inv["computed_total"], inv["vendor"], inv["ocr_engine"]) == \
        (675.0, 25.0, 700.0, 700.0, "DEMO MART", "RAPIDOCR"), inv
    assert inv["image_url"] == f"/deliveries/{order_a}/invoice-image" and "Cigarettes" in inv["raw_ocr_text"]
    assert client.get(f"/deliveries/{order_a.lower()}", headers=auth(guard)).status_code == 200
    assert client.get("/deliveries/NO-SUCH-ORDER", headers=auth(guard)).status_code == 404
    assert client.get(inv["image_url"]).status_code == 401
    img = client.get(inv["image_url"], headers=auth(guard))
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == png
    pdf_img = client.get(f"/deliveries/{order_pdf}/invoice-image", headers=auth(guard))
    assert pdf_img.status_code == 200 and pdf_img.headers["content-type"] == "image/png" and pdf_img.content.startswith(b"\x89PNG")
    print("  -> list filters (q, verdict, status=pending) work; summary carries counts, totals and reply text")
    print("  -> detail lines: Food/FOOD_OK/ALLOW ... Tobacco/TOBACCO_RESTRICTED/ALERT; invoice totals 675 + 25 = 700")
    print("  -> invoice image 401 without token, original PNG with it; PDF served as its rendered page 1")
    print("  -> PASS Scenario 7")

    # --- Scenario 8: Console upload + append-only decisions ---
    print("\n[SCENARIO 8] POST /deliveries/process (guard) and append-only POST /deliveries/{id}/decision...")
    order_c = f"P7-{tag}C"
    assert client.post("/deliveries/process", data={"order_id": order_c}, files={"file": ("i.png", png, "image/png")}).status_code == 401
    r = client.post("/deliveries/process", headers=auth(guard), data={"order_id": order_c, "gate_id": "GATE_2"},
                    files={"file": ("i.png", png, "image/png")})
    assert r.status_code == 201 and r.json()["source"] == "CONSOLE" and r.json()["gate_id"] == "GATE_2", r.text
    flags_mid = client.get("/dashboard/summary", headers=auth(guard)).json()["delivery_flags"]
    assert flags_mid == flags_before + 4, (flags_before, flags_mid)
    assert client.post(f"/deliveries/{order_c}/decision", json={"decision": "CLEARED"}).status_code == 401
    assert client.post(f"/deliveries/{order_c}/decision", headers=auth(guard), json={"decision": "OPEN_BARRIER"}).status_code == 422
    r = client.post(f"/deliveries/{order_c}/decision", headers=auth(guard), json={"decision": "HELD", "note": "Cigarettes not allowed in hostel"})
    assert r.status_code == 201 and r.json()["latest_decision"]["decision"] == "HELD", r.text
    r = client.post(f"/deliveries/{order_c}/decision", headers=auth(admin), json={"decision": "ESCALATED", "note": "Sent to supervisor"})
    dec = r.json()
    assert [x["decision"] for x in dec["decisions"]] == ["HELD", "ESCALATED"] and dec["decisions"][0]["by"] == "Phase 7 Guard"
    assert dec["latest_decision"]["decision"] == "ESCALATED" and dec["latest_decision"]["by"] == "Phase 7 Admin"
    with SessionLocal() as s2:
        row = s2.query(DeliveryDecision).join(DeliveryDecision.order).filter_by(order_id=order_c).first()
        try:
            s2.delete(row)
            s2.flush()
            raise AssertionError("ORM delete of a decision was not rejected")
        except ValueError:
            s2.rollback()
        for stmt in ("UPDATE delivery_decisions SET decision = 'CLEARED' WHERE id = :id", "DELETE FROM delivery_decisions WHERE id = :id"):
            try:
                s2.execute(text(stmt), {"id": row.id})
                raise AssertionError(f"database accepted: {stmt}")
            except AssertionError:
                raise
            except Exception:
                s2.rollback()
        triggers = {r[0] for r in s2.execute(text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'delivery_decisions'::regclass AND NOT tgisinternal"))}
        assert {"delivery_decisions_append_only", "delivery_decisions_reject_truncate"} <= triggers, triggers
    # Re-sending the invoice is a new submission: earlier decisions stay in history, the new one awaits a decision
    r = client.post("/deliveries/process", headers=auth(guard), data={"order_id": order_c}, files={"file": ("i.png", png, "image/png")})
    again = r.json()
    assert again["latest_decision"] is None and [x["decision"] for x in again["decisions"]] == ["HELD", "ESCALATED"]
    assert len(client.get("/deliveries", params={"q": order_c}, headers=auth(guard)).json()) == 1
    client.post(f"/deliveries/{order_c}/decision", headers=auth(guard), json={"decision": "CLEARED"})
    assert client.get("/deliveries", params={"q": order_c, "status": "CLEARED"}, headers=auth(guard)).json()[0]["order_id"] == order_c
    flags_after = client.get("/dashboard/summary", headers=auth(guard)).json()["delivery_flags"]
    assert flags_after == flags_mid - 1, (flags_mid, flags_after)
    print("  -> guard upload source=CONSOLE; dashboard delivery_flags +1 per flagged undecided delivery")
    print("  -> decisions HELD then ESCALATED both kept; unknown decision 422; ORM delete and SQL UPDATE/DELETE rejected,")
    print("     row and TRUNCATE triggers installed")
    print("  -> a re-sent invoice needs a fresh decision, history kept; deciding removes it from delivery_flags")
    print("  -> PASS Scenario 8")

    # --- Scenario 9: Unified alerts + slide-6 registry_match on the feed ---
    print("\n[SCENARIO 9] GET /alerts and registry_match on manual sightings...")
    assert client.get("/alerts").status_code == 401
    alerts = client.get("/alerts", params={"limit": 200}, headers=auth(guard)).json()
    mine = [a for a in alerts if a["ref"] == order_a]
    assert {(a["kind"], a["severity"]) for a in mine} == {("DELIVERY_ALERT", "HIGH"), ("DELIVERY_REVIEW", "MEDIUM")}, mine
    assert not [a for a in alerts if a["ref"] == order_c], "decided delivery still alerted"
    severity_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    assert [severity_rank[a["severity"]] for a in alerts] == sorted(severity_rank[a["severity"]] for a in alerts)

    base = new_plate()
    near = [base[:-1] + c for c in "28" if base[:-1] + c != base][:2]
    with SessionLocal() as s3:
        owner = VehicleOwner(identifier=f"P7-SID-{tag}", full_name=f"P7 Student {tag}", person_type=PersonType.STUDENT,
                             residence_type=ResidenceType.HOSTELLER, residence="BH-1")
        s3.add(owner)
        s3.flush()
        for p in [base] + near:
            s3.add(Vehicle(raw_plate=p, normalized_plate=p, vehicle_category=VehicleCategory.STUDENT, owner_id=owner.id))
        s3.commit()
    extra = base[:6] + "1" + base[6:]  # one extra character
    r = client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_2", "plate": extra, "direction": "UNKNOWN"})
    rm = r.json()["registry_match"]
    assert (rm["outcome"], rm["basis"], rm["edits"]) == ("LINKED", "ONE_EDIT", 1) and rm["owner"]["institutional_id"] == f"P7-SID-{tag}", rm
    assert r.json()["link_status"] == "NOT_LINKED"  # the 5C linkage is unchanged: fuzzy matches are never applied
    ambiguous = base[:-1]
    r = client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_2", "plate": ambiguous, "direction": "UNKNOWN"})
    assert r.json()["registry_match"]["outcome"] == "NEEDS_REVIEW" and len(r.json()["registry_match"]["candidates"]) >= 2
    test_reads = [r.json()["observation"]["id"]]
    stranger = new_plate("UP99")
    r = client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_1", "plate": stranger, "direction": "UNKNOWN"})
    assert r.json()["registry_match"]["outcome"] == "UNLINKED"
    test_reads.append(r.json()["observation"]["id"])
    exact = client.post("/observations/manual", headers=auth(guard), json={"gate_id": "GATE_1", "plate": base, "direction": "UNKNOWN"}).json()
    assert exact["registry_match"]["basis"] == "EXACT" and exact["link_status"] == "LINKED"
    alerts = client.get("/alerts", params={"limit": 200}, headers=auth(guard)).json()
    kinds = {a["ref"]: a["kind"] for a in alerts}
    assert kinds.get(ambiguous) == "PLATE_REVIEW" and kinds.get(stranger) == "PLATE_UNLINKED", kinds
    assert extra not in kinds and base not in kinds
    summary = client.get("/dashboard/summary", headers=auth(guard)).json()
    assert summary["plates_to_review"] >= 1 and summary["unlinked_plates"] >= 1 and "presence" in summary and "registry" in summary
    print(f"  -> {extra} LINKED by one edit (owner shown, link_status stays NOT_LINKED); {ambiguous} NEEDS REVIEW; {stranger} UNLINKED")
    print("  -> /alerts: DELIVERY_ALERT (HIGH) + DELIVERY_REVIEW (MEDIUM) for the undecided order, PLATE_REVIEW, PLATE_UNLINKED;")
    print("     decided orders and confident one-edit / exact reads are not listed; most severe first")
    print(f"  -> dashboard: delivery_flags={summary['delivery_flags']} plates_to_review={summary['plates_to_review']} unlinked_plates={summary['unlinked_plates']}")
    print("  -> PASS Scenario 9")

    # --- Scenario 10: WhatsApp webhook ---
    print("\n[SCENARIO 10] POST /webhooks/whatsapp (provider-agnostic, n8n can forward here)...")
    provider = client.get("/system/whatsapp", headers=auth(guard)).json()["provider"]
    assert client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"}).status_code == 403
    if provider in ("local", "mock"):
        order_w = f"P7-{tag}W"
        r = client.post("/webhooks/whatsapp", json={"from": "+919800000099", "text": f"Order {order_w}",
                                                    "media_base64": base64.b64encode(png).decode(), "media_mime": "image/png"})
        assert r.status_code == 200 and r.json()["status"] == "screened" and r.json()["order_id"] == order_w, r.text
        d = client.get(f"/deliveries/{order_w}", headers=auth(guard)).json()
        assert d["source"] == "WHATSAPP" and d["sender"] == "+919800000099" and d["overall"] == "ALERT"
        r = client.post("/webhooks/whatsapp", json={"from": "+919800000099", "text": "hello"})
        assert r.json()["status"] == "needs_invoice"
        r = client.post("/webhooks/whatsapp", json={"from": "+919800000099", "media_url": "http://169.254.169.254/latest"})
        assert r.json()["status"] == "needs_invoice"  # arbitrary URLs are never fetched
        printed = f"P7-{tag}N"
        r = client.post("/webhooks/whatsapp", json={"from": "+919800000099",
                                                    "media_base64": base64.b64encode(invoice_for(printed)).decode()})
        assert r.json()["status"] == "screened" and r.json()["order_id"] == printed, r.text  # order number read from the invoice
        print(f"  -> {provider}: photo + 'Order {order_w}' screened (source WHATSAPP); text-only and media_url-only get a request for the photo")
        print("  -> a photo without text uses the order number printed on the invoice")
    else:
        print(f"  -> provider {provider}: webhook format is Meta's; skipped the local payload checks")
    assert client.post("/webhooks/whatsapp", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 400
    print("  -> subscription check with a wrong token 403; non-JSON body 400")
    print("  -> PASS Scenario 10")

    # --- Scenario 11: Invariants ---
    print("\n[SCENARIO 11] Invariants: no access decisions, nothing blocked, history kept...")
    with SessionLocal() as s4:
        assert s4.query(AccessDecision).count() == access_decisions_start
        assert s4.query(DeliveryDecision).join(DeliveryDecision.order).filter_by(order_id=order_c).count() == 3
    print(f"  -> AccessDecision count unchanged ({access_decisions_start}); all 3 decisions on {order_c} still present")
    print("  -> PASS Scenario 11")

    # Close this suite's own test orders and reads (append-only decisions / resolutions; nothing is
    # deleted) so they do not crowd the demo console's alerts and stat tiles.
    closed = 0
    for d in client.get("/deliveries", params={"q": "P7-", "status": "undecided", "limit": 200}, headers=auth(guard)).json():
        if d["order_id"].startswith("P7-"):
            client.post(f"/deliveries/{d['order_id']}/decision", headers=auth(guard),
                        json={"decision": "CLEARED", "note": "Phase 7 test data, closed by the test suite"})
            closed += 1
    for obs_id in test_reads:
        client.post("/resolutions", headers=auth(guard), json={"observation_id": obs_id, "chosen_vehicle_id": "none",
                                                               "note": "Phase 7 test read"})
    print(f"\n  (cleanup: {closed} test deliveries marked CLEARED, {len(test_reads)} test reads resolved; history kept)")

    print("\n========================================================")
    print("PHASE 7: ALL 11 SCENARIOS PASSED")
    print("========================================================")

if __name__ == "__main__":
    server_thread = threading.Thread(target=start_backend, daemon=True)
    server_thread.start()
    wait_for_backend()

    try:
        run_tests()
    except Exception as e:
        print(f"\nTEST SUITE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    sys.exit(0)
