import base64
import io
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.models.enums import DeliverySource
from backend.app.models.gate import Gate
from backend.app.routes.deliveries import read_upload
from backend.app.schemas.delivery import DeliveryDetail
from backend.app.services.delivery_screening_service import delivery_screening_service
from backend.app.whatsapp import get_whatsapp_provider

# Phase 7: the LAN stand-in for WhatsApp. A rider (or the guard) opens http://<server>:8000/intake
# on a phone, types the order ID and uploads the invoice photo; the server screens it exactly as a
# chat message would be and shows the reply. Public on purpose (riders have no account), so it only
# accepts an upload and shows that upload's own result.

router = APIRouter(prefix="/intake", tags=["Delivery Intake"])

INTAKE_GATES = ("GATE_1", "GATE_2", "GATE_3")

_CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#16181d;--muted:#5b6170;--line:#dde0e6;--accent:#2457c5;--me:#dcf2d6;--bot:#fff;
--allow:#1d6b3a;--allow-bg:#e3f3e8;--review:#8a5a00;--review-bg:#fdf0d5;--alert:#a3221c;--alert-bg:#fbe3e1}
@media (prefers-color-scheme:dark){:root{--bg:#121418;--card:#1c1f25;--ink:#eceef2;--muted:#9aa1ae;--line:#2c3038;--accent:#7aa2ff;
--me:#1f3a26;--bot:#1c1f25;--allow:#8fd6a5;--allow-bg:#163222;--review:#f0c060;--review-bg:#3a2e12;--alert:#ff9a92;--alert-bg:#3d1a18}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:520px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:1.35rem;margin:4px 0 2px}p.sub{color:var(--muted);margin:0 0 18px;font-size:.92rem}
form,.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
label{display:block;font-weight:600;font-size:.9rem;margin:12px 0 6px}label:first-child{margin-top:0}
.hint{font-weight:400;color:var(--muted)}
input[type=text],input[type=tel],select{width:100%;font:inherit;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
input[type=file]{width:100%;font:inherit;padding:10px;border:1px dashed var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
button,.btn{display:block;width:100%;margin-top:18px;padding:13px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:600 1rem system-ui,sans-serif;text-align:center;text-decoration:none;cursor:pointer}
.note{color:var(--muted);font-size:.85rem;margin-top:14px}
.chat{display:flex;flex-direction:column;gap:10px;margin-bottom:16px}
.bubble{max-width:88%;padding:10px 12px;border-radius:14px;border:1px solid var(--line)}
.me{align-self:flex-end;background:var(--me);border-bottom-right-radius:4px}.bot{align-self:flex-start;background:var(--bot);border-bottom-left-radius:4px}
.bubble img{display:block;max-width:100%;border-radius:8px;margin-top:6px}.who{font-size:.75rem;color:var(--muted);margin-bottom:2px}
table{width:100%;border-collapse:collapse;font-size:.9rem}td{padding:8px 4px;border-top:1px solid var(--line);vertical-align:top}
td.num{text-align:right;white-space:nowrap}.meta{color:var(--muted);font-size:.8rem}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:700;letter-spacing:.02em}
.ALLOW{color:var(--allow);background:var(--allow-bg)}.REVIEW{color:var(--review);background:var(--review-bg)}.ALERT{color:var(--alert);background:var(--alert-bg)}
.err{border-color:var(--alert);color:var(--alert)}
"""

def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body><main>{body}</main></body></html>"
    )
    return HTMLResponse(html, status_code=status_code)

def _gate_options(db: Session) -> str:
    names = {g.id: g.name for g in db.query(Gate).filter(Gate.id.in_(INTAKE_GATES)).all()}
    options = ["<option value=''>Not sure</option>"]
    for gate_id in INTAKE_GATES:
        label = f"{gate_id.replace('_', ' ').title()}" + (f" · {names[gate_id]}" if gate_id in names else "")
        options.append(f"<option value='{gate_id}'>{escape(label)}</option>")
    return "".join(options)

@router.get("", response_class=HTMLResponse)
def intake_page(db: Session = Depends(get_db)):
    """Mobile page "Send delivery invoice" (stand-in for sending the invoice on WhatsApp)."""
    body = f"""
<h1>Send delivery invoice</h1>
<p class="sub">Campus gate delivery check. Send the order ID and a photo of the invoice; the guard sees the result.</p>
<form method="post" action="/intake/upload" enctype="multipart/form-data">
  <label for="order_id">Order ID</label>
  <input type="text" id="order_id" name="order_id" required maxlength="50" placeholder="e.g. D-20481" autocapitalize="characters" autocomplete="off">
  <label for="sender_phone">Your phone <span class="hint">(optional)</span></label>
  <input type="tel" id="sender_phone" name="sender_phone" maxlength="20" placeholder="+91 98xxx xxxxx" autocomplete="tel">
  <label for="gate_id">Gate</label>
  <select id="gate_id" name="gate_id">{_gate_options(db)}</select>
  <label for="file">Invoice photo or PDF</label>
  <input type="file" id="file" name="file" required accept="image/*,application/pdf">
  <button type="submit">Send invoice</button>
  <p class="note">The guard makes every decision. Nothing is blocked automatically.</p>
</form>"""
    return _page("Send delivery invoice", body)

def _thumbnail(content: bytes) -> Optional[str]:
    """Small JPEG data URI of the uploaded photo for the chat bubble (no second request needed)."""
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(content)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((480, 480))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - PDFs and odd files simply get no thumbnail
        return None

def _result_page(detail: DeliveryDetail, thumb: Optional[str], sender: Optional[str]) -> HTMLResponse:
    rows = "".join(
        f"<tr><td>{escape(i.item_name)}<div class='meta'>{escape(i.category_label)} · {escape(i.reason_code)}</div></td>"
        f"<td class='num'>{i.quantity if i.quantity is not None else '?'}</td>"
        f"<td class='num'>{f'{i.amount:.2f}' if i.amount is not None else '?'}</td>"
        f"<td class='num'><span class='pill {i.verdict.value}'>{i.verdict.value}</span></td></tr>"
        for i in detail.items
    ) or "<tr><td colspan='4'>No item lines could be read.</td></tr>"
    totals = []
    inv = detail.invoice
    for label, value in (("Subtotal", inv.subtotal), ("Delivery", inv.delivery_fee), ("Total", inv.total), ("Lines add up to", inv.computed_total)):
        if value is not None:
            totals.append(f"<tr><td colspan='2'>{label}</td><td class='num'>{value:.2f}</td><td></td></tr>")
    image = f"<img src='{thumb}' alt='Invoice photo'>" if thumb else "<div class='meta'>Invoice file attached</div>"
    body = f"""
<h1>Invoice sent</h1>
<p class="sub">Order {escape(detail.order_id)}{(' · ' + escape(detail.gate_id)) if detail.gate_id else ''}</p>
<div class="chat">
  <div class="bubble me"><div class="who">{escape(sender or 'You')}</div>Order {escape(detail.order_id)}{image}</div>
  <div class="bubble bot"><div class="who">Campus gate</div>{escape(detail.reply_text)}</div>
</div>
<div class="card">
  <table><tr><td><b>Item</b></td><td class="num"><b>Qty</b></td><td class="num"><b>Amount</b></td><td class="num"><b>Check</b></td></tr>{rows}{''.join(totals)}</table>
  <p class="note">Read with {escape(inv.ocr_engine or 'OCR')}. The guard decides; nothing is blocked automatically.</p>
</div>
<a class="btn" href="/intake">Send another invoice</a>"""
    return _page(f"Order {detail.order_id}", body, status_code=201)

def _public_json(detail: DeliveryDetail) -> dict:
    """What the sender may see: their own screening result, without guard names or raw OCR text."""
    return {
        "order_id": detail.order_id,
        "reply_text": detail.reply_text,
        "overall": detail.overall.value,
        "line_count": detail.line_count,
        "review_count": detail.review_count,
        "alert_count": detail.alert_count,
        "totals_match": detail.totals_match,
        "total_amount": detail.total_amount,
        "computed_total": detail.invoice.computed_total,
        "ocr_engine": detail.invoice.ocr_engine,
        "items": [i.model_dump(mode="json") for i in detail.items],
    }

def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept

def screen_and_reply(db: Session, *, order_id: Optional[str], content: bytes, source: DeliverySource,
                     sender: Optional[str], gate_id: Optional[str], platform: Optional[str] = None) -> DeliveryDetail:
    """Shared by the intake page and the WhatsApp webhook: screen, then send the chat reply."""
    invoice = delivery_screening_service.process(db, order_id=order_id, content=content, source=source,
                                                 sender=sender, gate_id=gate_id, platform=platform)
    detail = delivery_screening_service.detail(db, invoice.order.order_id)
    provider = get_whatsapp_provider()
    if sender or provider.name != "meta":  # local / mock keep the reply in their outbox
        provider.send_message(sender or "intake-page", detail.reply_text)
    return detail

@router.post("/upload", status_code=201)
async def intake_upload(
    request: Request,
    order_id: str = Form(..., max_length=50),
    file: UploadFile = File(...),
    sender_phone: Optional[str] = Form(None, max_length=20),
    gate_id: Optional[str] = Form(None, max_length=30),
    platform: Optional[str] = Form(None, max_length=20),
    db: Session = Depends(get_db),
):
    """Screens an uploaded invoice like a WhatsApp message. HTML chat-style result, or JSON with Accept: application/json."""
    content = await read_upload(file)
    as_json = _wants_json(request)
    try:
        detail = await run_in_threadpool(
            screen_and_reply, db, order_id=order_id, content=content, source=DeliverySource.LOCAL_INTAKE,
            sender=sender_phone, gate_id=gate_id, platform=platform,
        )
    except HTTPException as exc:
        if as_json:
            raise
        body = (f"<h1>Could not send</h1><div class='card err'>{escape(str(exc.detail))}</div>"
                "<a class='btn' href='/intake'>Try again</a>")
        return _page("Could not send", body, status_code=exc.status_code)
    if as_json:
        return JSONResponse(_public_json(detail), status_code=201)
    return _result_page(detail, await run_in_threadpool(_thumbnail, content), sender_phone)
