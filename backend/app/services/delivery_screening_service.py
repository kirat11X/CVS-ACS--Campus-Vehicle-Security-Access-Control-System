import io
import logging
import re
import subprocess  # nosec B404
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.config import INVOICE_MAX_UPLOAD_MB, MEDIA_ROOT
from backend.app.models.delivery import DeliveryDecision, DeliveryOrder, Invoice, InvoiceItem
from backend.app.models.enums import DeliverySource, GuardDecision, OrderStatus, PlatformType, ScreeningVerdict
from backend.app.models.gate import Gate
from backend.app.schemas.delivery import (
    DecisionRecord,
    DeliveryDetail,
    DeliveryItem,
    DeliveryItemsUpdate,
    DeliverySummary,
    InvoiceInfo,
    ItemEdit,
)
from backend.app.services.cvs_acs_screener import cvs_acs_screener
from backend.app.services.delivery_policy import CATEGORY_LABELS, screen_line, worst
from backend.app.services.invoice_reader import (
    OcrResult,
    ParsedInvoice,
    ParsedLine,
    extract_pdf_digital_text,
    normalize_order_id,
    parse_rows,
    read_image,
)
from backend.app.services.llm_invoice_extractor import llm_invoice_extractor

logger = logging.getLogger("campus_security.delivery")

ORDER_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,49}$")
_TOLERANCE = Decimal("0.01")
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"%PDF-", "pdf"),
)

@dataclass
class ScreenedLine:
    line_no: int
    item_name: str
    quantity: Optional[int]
    unit_price: Optional[Decimal]
    amount: Optional[Decimal]
    category: str
    reason_code: str
    verdict: ScreeningVerdict
    confidence: Optional[float]

@dataclass
class ScreeningResult:
    lines: List[ScreenedLine]
    parsed: ParsedInvoice
    computed_total: Optional[Decimal]
    totals_match: Optional[bool]
    overall: ScreeningVerdict
    order_id_on_invoice: Optional[str]

def _money(value: Optional[Decimal]) -> str:
    return f"{value:.2f}" if value is not None else "?"

def _float(value) -> Optional[float]:
    return float(value) if value is not None else None

class DeliveryScreeningService:
    """
    Phase 7: delivery invoice screening.

    invoice photo -> OCR (RapidOCR, Tesseract fallback) -> line items + totals -> deterministic
    policy table per line (ALLOW / REVIEW / ALERT with a reason code) -> stored with the order.
    The screening proposes; the guard decides (append-only DeliveryDecision). Nothing is ever
    blocked automatically and no barrier is controlled.
    """

    # ---------------------------------------------------------------- pure screening

    @staticmethod
    def screen(parsed: ParsedInvoice, order_id: Optional[str] = None) -> ScreeningResult:
        lines = []
        for line in parsed.lines:
            if not line.readable:
                s_cat = "UNKNOWN"
                s_reason = "UNREADABLE_LINE"
                s_verdict = ScreeningVerdict.REVIEW
            else:
                scr = cvs_acs_screener.screen_item(line.item_name)
                s_cat = scr.get("category", "FOOD_PREPARED")
                s_reason = scr.get("risk_tag", "SAFE_FOOD")
                verd_str = str(scr.get("verdict", "ALLOW")).upper()
                try:
                    s_verdict = ScreeningVerdict(verd_str)
                except ValueError:
                    s_verdict = ScreeningVerdict.REVIEW

            lines.append(ScreenedLine(
                line_no=line.line_no, item_name=line.item_name, quantity=line.quantity, unit_price=line.unit_price,
                amount=line.amount, category=s_cat, reason_code=s_reason, verdict=s_verdict,
                confidence=line.confidence,
            ))

        # Arithmetic check: lines (+ delivery fee + tax - discount) must give the printed total.
        amounts = [l.amount for l in lines]
        computed_total = None
        totals_match: Optional[bool] = None
        if lines and all(a is not None for a in amounts):
            items_sum = sum(amounts, Decimal("0.00"))
            computed_total = items_sum + (parsed.delivery_fee or 0) + (parsed.tax or 0) - (parsed.discount or 0)
            checks = []
            if parsed.subtotal is not None:
                checks.append(abs(items_sum - parsed.subtotal) <= _TOLERANCE)
            if parsed.total is not None:
                checks.append(abs(computed_total - parsed.total) <= _TOLERANCE)
            totals_match = all(checks) if checks else None
        elif lines and (parsed.total is not None or parsed.subtotal is not None):
            totals_match = False  # a line amount could not be read, so the total cannot be confirmed

        overall = worst(l.verdict for l in lines) if lines else ScreeningVerdict.REVIEW
        mismatch_order = bool(
            order_id
            and not order_id.startswith("TG-")
            and parsed.order_number
            and not parsed.order_number.startswith("TG-")
            and normalize_order_id(order_id) != normalize_order_id(parsed.order_number)
        )
        if not lines or mismatch_order:
            overall = worst([overall, ScreeningVerdict.REVIEW])
        return ScreeningResult(lines, parsed, computed_total, totals_match, overall, parsed.order_number)

    @staticmethod
    def reply_text(order_id: str, result: ScreeningResult) -> str:
        """The chat reply, e.g. 'Order D-20481: 2 of 5 lines need a look. Total matches: 700.00.'"""
        n = len(result.lines)
        if n == 0:
            return f"Order {order_id}: no item lines could be read. The guard will check the invoice by hand."
        flagged = sum(1 for l in result.lines if l.verdict != ScreeningVerdict.ALLOW)
        if flagged == 0:
            text = f"Order {order_id}: all {n} lines look fine."
        else:
            text = f"Order {order_id}: {flagged} of {n} {'line needs' if flagged == 1 else 'lines need'} a look."
        p = result.parsed
        if result.totals_match is True:
            text += f" Total matches: {_money(p.total if p.total is not None else result.computed_total)}."
        elif result.totals_match is False:
            if result.computed_total is None:
                text += f" A line amount could not be read, so the total ({_money(p.total or p.subtotal)}) is not confirmed."
            else:
                printed = p.total if p.total is not None else p.subtotal
                text += f" Total does not add up: lines give {_money(result.computed_total)}, invoice says {_money(printed)}."
        else:
            text += " No invoice total could be read to check."
        if result.order_id_on_invoice and result.order_id_on_invoice != normalize_order_id(order_id):
            text += f" The invoice shows order {result.order_id_on_invoice}."
        return text

    # ---------------------------------------------------------------- files

    @staticmethod
    def _sniff(content: bytes) -> Optional[str]:
        for sig, ext in _SIGNATURES:
            if content.startswith(sig):
                return ext
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "webp"
        return None

    def store_upload(self, content: bytes) -> Tuple[str, Optional[str]]:
        """Validates and saves an upload under media/invoices/. Returns (path, png preview path) relative to MEDIA_ROOT."""
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty.")
        if len(content) > INVOICE_MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Invoice files are limited to {INVOICE_MAX_UPLOAD_MB:g} MB.")
        ext = self._sniff(content)
        if ext is None:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Send the invoice as a JPG, PNG, WEBP photo or a PDF.")
        if ext != "pdf":
            from PIL import Image, UnidentifiedImageError
            try:
                with Image.open(io.BytesIO(content)) as img:
                    img.verify()
            except (UnidentifiedImageError, OSError, SyntaxError):
                raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="The image could not be opened.")

        folder = MEDIA_ROOT / "invoices"
        folder.mkdir(parents=True, exist_ok=True)
        stem = uuid.uuid4().hex
        path = folder / f"{stem}.{ext}"
        path.write_bytes(content)
        preview = None
        if ext == "pdf":
            preview = self._render_pdf(path, folder / f"{stem}_page1")
        return str(path.relative_to(MEDIA_ROOT)), (str(preview.relative_to(MEDIA_ROOT)) if preview else None)

    @staticmethod
    def _render_pdf(pdf: Path, out_stem: Path) -> Optional[Path]:
        """Page 1 -> PNG with poppler's pdftoppm (installed on the host). None if that fails."""
        try:
            subprocess.run(  # nosec B603 B607
                ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "1", "-singlefile", str(pdf), str(out_stem)],
                check=True, timeout=30, capture_output=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Could not render PDF %s: %s", pdf, exc)
            return None
        png = out_stem.with_suffix(".png")
        return png if png.exists() else None

    @staticmethod
    def media_file(relative: Optional[str]) -> Optional[Path]:
        if not relative:
            return None
        root = MEDIA_ROOT.resolve()
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    # ---------------------------------------------------------------- write path

    def process(
        self,
        db: Session,
        *,
        order_id: Optional[str],
        content: bytes,
        source: DeliverySource,
        sender: Optional[str] = None,
        gate_id: Optional[str] = None,
        platform: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        customer_name: Optional[str] = None,
        customer_id: Optional[uuid.UUID] = None,
    ) -> Invoice:
        """
        Screens one invoice and stores it as the order's latest submission. Without an order ID
        (a chat photo with no text) the order number printed on the invoice is used, if readable.
        """
        oid = normalize_order_id(order_id)
        if oid and not ORDER_ID_PATTERN.match(oid):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order ID must be letters, digits and dashes (e.g. D-20481).")
        gate_id = (gate_id or "").strip().upper() or None
        if gate_id and not db.get(Gate, gate_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown gate '{gate_id}'.")
        try:
            platform_value = PlatformType((platform or "OTHER").strip().upper())
        except ValueError:
            platform_value = PlatformType.OTHER
        sender = (sender or "").strip()[:50] or None

        image_rel, preview_rel = self.store_upload(content)
        orig_file = self.media_file(image_rel)
        if orig_file and orig_file.suffix == ".pdf":
            # 1. Direct digital text extraction from PDF (fast, 0 OCR artifacts)
            ocr = extract_pdf_digital_text(orig_file)
            if not ocr or not ocr.rows:
                # Scanned PDF: fall back to image OCR on rendered page 1
                ocr_path = self.media_file(preview_rel)
                ocr = read_image(ocr_path) if ocr_path else OcrResult("NONE", [], None)
            parsed = parse_rows(ocr.rows)
        else:
            # 2. Photos / mobile screenshots:
            # Pickup pipeline: extracts all raw text via OCR, then local LLM analyzes it
            ocr_path = self.media_file(preview_rel or image_rel)
            ocr = read_image(ocr_path) if ocr_path else OcrResult("NONE", [], None)

            if llm_invoice_extractor.is_available() and ocr.text.strip():
                parsed = llm_invoice_extractor.extract_from_text(ocr.text)
                if not parsed or not parsed.lines:
                    parsed = parse_rows(ocr.rows)
            else:
                parsed = parse_rows(ocr.rows)

        if not oid:
            oid = parsed.order_number or ""
            if not ORDER_ID_PATTERN.match(oid):
                oid = f"TG-{uuid.uuid4().hex[:8].upper()}"
        result = self.screen(parsed, oid)
        reply = self.reply_text(oid, result)

        order = self._get_or_create_order(db, oid, platform_value, gate_id, sender)
        invoice = Invoice(
            order_id=order.id,
            image_path=image_rel,
            preview_path=preview_rel,
            raw_ocr_text=ocr.text,
            confidence=ocr.confidence if ocr.confidence is not None else 0.0,
            vendor=result.parsed.vendor,
            subtotal=result.parsed.subtotal,
            tax=result.parsed.tax,
            total_amount=result.parsed.total,
            source=source,
            sender=sender,
            gate_id=gate_id,
            ocr_engine=ocr.engine,
            delivery_fee=result.parsed.delivery_fee,
            computed_total=result.computed_total,
            totals_match=result.totals_match,
            overall_verdict=result.overall,
            reply_text=reply,
            created_by_id=user_id,
        )
        invoice.items = [
            InvoiceItem(
                item_name=l.item_name, quantity=l.quantity, unit_price=l.unit_price, total_price=l.amount,
                line_no=l.line_no, category=l.category, reason_code=l.reason_code, verdict=l.verdict, confidence=l.confidence,
            )
            for l in result.lines
        ]
        db.add(invoice)
        order.status = OrderStatus.OCR_PROCESSED if result.overall == ScreeningVerdict.ALLOW else OrderStatus.REVIEW
        if customer_name:
            order.customer_name = customer_name
        if customer_id:
            order.customer_id = customer_id
        if result.parsed.restaurant:
            order.restaurant = result.parsed.restaurant
        elif result.parsed.vendor:
            order.restaurant = result.parsed.vendor

        if result.parsed.platform:
            plat_upper = result.parsed.platform.strip().upper()
            try:
                order.platform = PlatformType(plat_upper)
            except ValueError:
                if "SWIGGY" in plat_upper:
                    order.platform = PlatformType.SWIGGY
                elif "ZOMATO" in plat_upper:
                    order.platform = PlatformType.ZOMATO
                elif "BLINKIT" in plat_upper:
                    order.platform = PlatformType.BLINKIT
                elif "ZEPTO" in plat_upper:
                    order.platform = PlatformType.ZEPTO
                elif "INSTAMART" in plat_upper:
                    order.platform = PlatformType.INSTAMART
        if gate_id:
            order.gate_id = gate_id
        db.commit()
        db.refresh(invoice)
        return invoice

    @staticmethod
    def _get_or_create_order(db: Session, oid: str, platform: PlatformType, gate_id: Optional[str], sender: Optional[str]) -> DeliveryOrder:
        order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == oid).first()
        if order:
            return order
        order = DeliveryOrder(order_id=oid, platform=platform, gate_id=gate_id, delivery_agent_phone=(sender or None) and sender[:20])
        db.add(order)
        try:
            db.flush()
        except IntegrityError:  # created concurrently by another submission
            db.rollback()
            order = db.query(DeliveryOrder).filter(DeliveryOrder.order_id == oid).one()
        return order

    def record_decision(self, db: Session, order_id: str, decision: GuardDecision, note: Optional[str], user_id: uuid.UUID) -> DeliveryDetail:
        order, invoice = self._current(db, order_id)
        db.add(DeliveryDecision(
            order_id=order.id, invoice_id=invoice.id, decision=decision,
            note=(note or "").strip() or None, decided_by_id=user_id,
        ))
        db.commit()
        return self.detail(db, order_id)

    def update_items(
        self,
        db: Session,
        order_id: str,
        body: DeliveryItemsUpdate,
        user_id: uuid.UUID,
    ) -> DeliveryDetail:
        """
        Allows staff/guards to edit extracted items, quantities, or amounts on the portal.
        Re-evaluates contraband safety policies and updates the invoice.
        """
        order, invoice = self._current(db, order_id)

        # Remove existing invoice items cleanly
        for existing in list(invoice.items):
            db.delete(existing)
        db.flush()

        new_items = []
        screened_lines = []
        for idx, it in enumerate(body.items, start=1):
            qty = it.quantity or 1
            amt = Decimal(str(it.amount)) if it.amount is not None else None
            unit = (amt / Decimal(qty)).quantize(Decimal("0.01")) if amt is not None else None
            sline = screen_line(it.item_name)
            screened_lines.append(sline)
            new_items.append(
                InvoiceItem(
                    invoice_id=invoice.id,
                    line_no=idx,
                    item_name=it.item_name,
                    quantity=qty,
                    unit_price=unit,
                    total_price=amt,
                    category=sline.category,
                    reason_code=sline.reason_code,
                    verdict=sline.verdict,
                    confidence=1.0,
                )
            )

        invoice.items = new_items
        computed = sum((it.total_price for it in new_items if it.total_price is not None), Decimal("0.00"))
        invoice.computed_total = computed

        if body.total_amount is not None:
            invoice.total_amount = Decimal(str(body.total_amount))
        elif computed > Decimal("0.00"):
            invoice.total_amount = computed

        if body.vendor:
            invoice.vendor = body.vendor
            if not order.restaurant:
                order.restaurant = body.vendor

        overall_verdict = worst([l.verdict for l in screened_lines]) if screened_lines else ScreeningVerdict.ALLOW
        if invoice.total_amount is not None and abs(computed - invoice.total_amount) > _TOLERANCE:
            overall_verdict = worst([overall_verdict, ScreeningVerdict.REVIEW])
            invoice.totals_match = False
        else:
            invoice.totals_match = True

        invoice.overall_verdict = overall_verdict
        order.status = OrderStatus.OCR_PROCESSED if overall_verdict == ScreeningVerdict.ALLOW else OrderStatus.REVIEW

        db.commit()
        return self.detail(db, order_id)

    # ---------------------------------------------------------------- read path

    @staticmethod
    def _latest_invoice_query(db: Session):
        latest = (
            db.query(Invoice.order_id.label("order_id"), func.max(Invoice.created_at).label("latest"))
            .filter(Invoice.source.isnot(None))
            .group_by(Invoice.order_id)
            .subquery()
        )
        return (
            db.query(Invoice)
            .join(latest, and_(Invoice.order_id == latest.c.order_id, Invoice.created_at == latest.c.latest))
            .join(DeliveryOrder, DeliveryOrder.id == Invoice.order_id)
            .filter(Invoice.source.isnot(None))
        )

    def _current(self, db: Session, order_id: str) -> Tuple[DeliveryOrder, Invoice]:
        oid = normalize_order_id(order_id)
        invoice = (
            self._latest_invoice_query(db)
            .options(selectinload(Invoice.items), selectinload(Invoice.order))
            .filter(DeliveryOrder.order_id == oid)
            .first()
        )
        if invoice is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No screened delivery for order '{oid}'.")
        return invoice.order, invoice

    @staticmethod
    def _decisions(db: Session, order_ids) -> Dict[uuid.UUID, List[DeliveryDecision]]:
        rows = (
            db.query(DeliveryDecision)
            .options(selectinload(DeliveryDecision.decided_by))
            .filter(DeliveryDecision.order_id.in_(list(order_ids)))
            .order_by(DeliveryDecision.decided_at.asc())
            .all()
        ) if order_ids else []
        out: Dict[uuid.UUID, List[DeliveryDecision]] = {}
        for d in rows:
            out.setdefault(d.order_id, []).append(d)
        return out

    @staticmethod
    def _decision_record(d: DeliveryDecision) -> DecisionRecord:
        by = d.decided_by.full_name if d.decided_by else "unknown"
        return DecisionRecord(decision=d.decision, note=d.note, by=by, at=d.decided_at)

    def _summary_fields(self, invoice: Invoice, decisions: List[DeliveryDecision]) -> dict:
        items = invoice.items
        current = [d for d in decisions if d.invoice_id == invoice.id]  # a resubmitted invoice needs a new decision
        return dict(
            order_id=invoice.order.order_id,
            platform=invoice.order.platform.value,
            gate_id=invoice.gate_id or invoice.order.gate_id,
            source=invoice.source,
            sender=invoice.sender,
            received_at=invoice.created_at,
            line_count=len(items),
            review_count=sum(1 for i in items if i.verdict == ScreeningVerdict.REVIEW),
            alert_count=sum(1 for i in items if i.verdict == ScreeningVerdict.ALERT),
            overall=invoice.overall_verdict or ScreeningVerdict.REVIEW,
            totals_match=invoice.totals_match,
            total_amount=_float(invoice.total_amount),
            latest_decision=self._decision_record(current[-1]) if current else None,
            reply_text=invoice.reply_text or "",
        )

    def list_deliveries(
        self,
        db: Session,
        status_filter: Optional[str] = None,
        verdict: Optional[ScreeningVerdict] = None,
        q: Optional[str] = None,
        limit: int = 50,
    ) -> List[DeliverySummary]:
        query = self._latest_invoice_query(db).options(selectinload(Invoice.items), selectinload(Invoice.order))
        if verdict is not None:
            query = query.filter(Invoice.overall_verdict == verdict)
        if q:
            like = f"%{q.strip().upper().replace('%', '').replace('_', '')}%"
            query = query.filter(DeliveryOrder.order_id.like(like))
        invoices = query.order_by(Invoice.created_at.desc()).all()
        decisions = self._decisions(db, {i.order_id for i in invoices})
        result = []
        for inv in invoices:
            summary = DeliverySummary(**self._summary_fields(inv, decisions.get(inv.order_id, [])))
            if not self._status_matches(summary, status_filter):
                continue
            result.append(summary)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _status_matches(summary: DeliverySummary, status_filter: Optional[str]) -> bool:
        """status: pending (flagged, no decision yet), decided, or a decision value (CLEARED / HELD / ESCALATED)."""
        if not status_filter:
            return True
        s = status_filter.strip().upper()
        if s == "PENDING":
            return summary.latest_decision is None and summary.overall != ScreeningVerdict.ALLOW
        if s == "DECIDED":
            return summary.latest_decision is not None
        if s == "UNDECIDED":
            return summary.latest_decision is None
        return summary.latest_decision is not None and summary.latest_decision.decision.value == s

    def detail(self, db: Session, order_id: str) -> DeliveryDetail:
        order, invoice = self._current(db, order_id)
        decisions = self._decisions(db, [order.id]).get(order.id, [])
        fields = self._summary_fields(invoice, decisions)
        return DeliveryDetail(
            **fields,
            invoice=InvoiceInfo(
                image_url=f"/deliveries/{quote(order.order_id, safe='')}/invoice-image",
                ocr_engine=invoice.ocr_engine,
                ocr_confidence=invoice.confidence if invoice.ocr_engine and invoice.ocr_engine != "NONE" else None,
                raw_ocr_text=invoice.raw_ocr_text or "",
                vendor=invoice.vendor,
                subtotal=_float(invoice.subtotal),
                delivery_fee=_float(invoice.delivery_fee),
                total=_float(invoice.total_amount),
                computed_total=_float(invoice.computed_total),
            ),
            items=[
                DeliveryItem(
                    line_no=i.line_no or n, item_name=i.item_name, quantity=i.quantity, amount=_float(i.total_price),
                    category=i.category or "UNKNOWN", category_label=CATEGORY_LABELS.get(i.category or "UNKNOWN", "Unknown"),
                    reason_code=i.reason_code or "UNKNOWN_CATEGORY", verdict=i.verdict or ScreeningVerdict.REVIEW,
                    confidence=i.confidence,
                )
                for n, i in enumerate(invoice.items, 1)
            ],
            decisions=[self._decision_record(d) for d in decisions],
        )

    def invoice_image(self, db: Session, order_id: str) -> Tuple[Path, str]:
        _, invoice = self._current(db, order_id)
        path = self.media_file(invoice.preview_path) or self.media_file(invoice.image_path)
        if path is None:
            fallback = MEDIA_ROOT / "test_invoice.png"
            if fallback.is_file():
                return fallback, "image/png"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The invoice file is no longer available.")
        media_type = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".pdf": "application/pdf"}.get(path.suffix, "application/octet-stream")
        return path, media_type

    def pending_invoices(self, db: Session, since=None) -> List[Invoice]:
        """Current invoices screened REVIEW/ALERT with no guard decision on that invoice yet."""
        query = (
            self._latest_invoice_query(db)
            .options(selectinload(Invoice.items), selectinload(Invoice.order))
            .filter(
                Invoice.overall_verdict.in_([ScreeningVerdict.REVIEW, ScreeningVerdict.ALERT]),
                ~exists().where(DeliveryDecision.invoice_id == Invoice.id),
            )
        )
        if since is not None:
            query = query.filter(Invoice.created_at >= since)
        return query.order_by(Invoice.created_at.desc()).all()

    def pending_flag_count(self, db: Session) -> int:
        return (
            self._latest_invoice_query(db)
            .filter(
                Invoice.overall_verdict.in_([ScreeningVerdict.REVIEW, ScreeningVerdict.ALERT]),
                ~exists().where(DeliveryDecision.invoice_id == Invoice.id),
            )
            .with_entities(func.count(Invoice.id))
            .scalar()
        ) or 0

delivery_screening_service = DeliveryScreeningService()
