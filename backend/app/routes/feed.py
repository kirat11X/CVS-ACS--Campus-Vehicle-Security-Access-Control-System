import asyncio
from pathlib import Path
from typing import AsyncIterator, Optional
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.orm import Session

from backend.app.config import FEED_STREAM_POLL_SECONDS, FRIGATE_HOST, FRIGATE_PORT, MEDIA_ROOT
from backend.app.db import SessionLocal
from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.enums import ObservationSource
from backend.app.models.observation import ObservationEvent
from backend.app.schemas.feed import FeedPage
from backend.app.services.feed_service import feed_service
from backend.app.services.visitor_service import check_and_trigger_visitor_overstay_alerts

router = APIRouter(prefix="/feed", tags=["Live Feed"])

@router.get("", response_model=FeedPage)
def get_feed(
    since_id: Optional[int] = Query(None, ge=0, description="Cursor from a previous page; omit for a snapshot"),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """
    Without since_id: the latest observations with their registry linkage, plus a cursor.
    With since_id: observations whose linkage view changed after that cursor (polling fallback).
    """
    try:
        check_and_trigger_visitor_overstay_alerts(db)
    except Exception:
        pass

    if since_id is None:
        return feed_service.snapshot(db, limit=limit)
    return feed_service.changes_since(db, since_id, limit=limit)

def _current_cursor() -> int:
    with SessionLocal() as db:
        return feed_service.current_cursor(db)

def _changes_since(cursor: int) -> FeedPage:
    with SessionLocal() as db:
        return feed_service.changes_since(db, cursor)

@router.get("/stream", response_class=EventSourceResponse)
async def stream_feed(
    request: Request,
    since_id: Optional[int] = Query(None, ge=0, description="Resume after this cursor"),
    last_event_id: Optional[str] = Header(None, description="Sent by EventSource on reconnect; wins over since_id"),
    user: CurrentUser = Depends(require_staff),
) -> AsyncIterator[ServerSentEvent]:
    """
    Server-Sent Events: one `feed` event per changed observation, `id` = cursor.
    An update to an existing observation (same source_event_id) carries the same
    item.observation.id as before, so clients replace the item instead of adding one.
    """
    cursor = since_id
    if last_event_id and last_event_id.strip().isdigit():
        cursor = int(last_event_id.strip())
    if cursor is None:
        cursor = await run_in_threadpool(_current_cursor)

    yield ServerSentEvent(event="ready", data={"cursor": cursor}, retry=3000)
    while not await request.is_disconnected():
        page = await run_in_threadpool(_changes_since, cursor)
        for entry in page.entries:
            yield ServerSentEvent(event="feed", id=str(entry.cursor), data=entry)
        cursor = page.cursor
        if not page.has_more:
            await asyncio.sleep(FEED_STREAM_POLL_SECONDS)

@router.get("/snapshots/{observation_id}")
def get_observation_snapshot(
    observation_id: UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_staff),
):
    """Proxies the camera snapshot (Frigate or live stream runner) with local fallback."""
    obs = db.get(ObservationEvent, observation_id)
    if not obs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Observation '{observation_id}' not found.")
    if obs.source == ObservationSource.MANUAL and not obs.source_event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation has no camera snapshot.")

    # Check local disk cache first
    local_candidates = [
        MEDIA_ROOT / "snapshots" / f"{obs.id}.jpg",
        (MEDIA_ROOT / "snapshots" / f"{obs.source_event_id}.jpg") if obs.source_event_id else None,
        (MEDIA_ROOT / "frigate" / f"{obs.source_event_id}.jpg") if obs.source_event_id else None,
        (MEDIA_ROOT / "frigate" / f"{obs.source_event_id}.png") if obs.source_event_id else None,
        MEDIA_ROOT / "test_plate.png",
    ]
    for p in local_candidates:
        if p and p.is_file():
            return FileResponse(p, media_type="image/jpeg" if p.suffix == ".jpg" else "image/png")

    if obs.source == ObservationSource.FRIGATE and obs.source_event_id:
        base = f"http://{FRIGATE_HOST}:{FRIGATE_PORT}/api/events/{quote(obs.source_event_id, safe='')}"
        try:
            with httpx.Client(timeout=1.0) as client:
                for name in ("snapshot.jpg", "thumbnail.jpg"):
                    resp = client.get(f"{base}/{name}")
                    content_type = resp.headers.get("content-type", "")
                    if resp.status_code == 200 and content_type.startswith("image/"):
                        return Response(
                            content=resp.content,
                            media_type=content_type,
                            headers={"Cache-Control": "private, max-age=60"},
                        )
        except (httpx.HTTPError, OSError):
            pass

    # Clean SVG camera placeholder when Frigate is offline
    plate_label = obs.raw_plate or obs.normalized_plate or "ANPR CAM"
    gate_label = obs.gate_id or "GATE-1"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" viewBox="0 0 320 240">'
        f'<rect width="320" height="240" fill="#0f172a"/>'
        f'<rect x="20" y="20" width="280" height="200" rx="8" fill="#1e293b" stroke="#334155" stroke-width="2"/>'
        f'<circle cx="160" cy="95" r="32" fill="#334155"/>'
        f'<circle cx="160" cy="95" r="16" fill="#0ea5e9"/>'
        f'<text x="160" y="155" text-anchor="middle" fill="#f8fafc" font-family="monospace" font-size="16" font-weight="bold">{plate_label}</text>'
        f'<text x="160" y="180" text-anchor="middle" fill="#94a3b8" font-family="sans-serif" font-size="12">{gate_label} • CAMERA FEED</text>'
        f'</svg>'
    )
    return Response(content=svg.encode("utf-8"), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=10"})
