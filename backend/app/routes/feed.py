import asyncio
from typing import AsyncIterator, Optional
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.orm import Session

from backend.app.config import FEED_STREAM_POLL_SECONDS, FRIGATE_HOST, FRIGATE_PORT
from backend.app.db import SessionLocal
from backend.app.dependencies import CurrentUser, get_db, require_staff
from backend.app.models.enums import ObservationSource
from backend.app.models.observation import ObservationEvent
from backend.app.schemas.feed import FeedPage
from backend.app.services.feed_service import feed_service

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
    """Proxies the Frigate snapshot (or thumbnail) for a camera observation."""
    obs = db.get(ObservationEvent, observation_id)
    if not obs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Observation '{observation_id}' not found.")
    if obs.source != ObservationSource.FRIGATE or not obs.source_event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation has no camera snapshot.")

    base = f"http://{FRIGATE_HOST}:{FRIGATE_PORT}/api/events/{quote(obs.source_event_id, safe='')}"
    try:
        with httpx.Client(timeout=3.0) as client:
            for name in ("snapshot.jpg", "thumbnail.jpg"):
                resp = client.get(f"{base}/{name}")
                content_type = resp.headers.get("content-type", "")
                if resp.status_code == 200 and content_type.startswith("image/"):
                    return Response(
                        content=resp.content,
                        media_type=content_type,
                        headers={"Cache-Control": "private, max-age=60"},
                    )
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Frigate is unreachable.")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Frigate has no snapshot for this event.")
