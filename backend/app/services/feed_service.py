from typing import Iterable, List
from uuid import UUID
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from backend.app.models.observation import ObservationEvent, ObservationFeedEvent
from backend.app.schemas.feed import FeedEntry, FeedPage
from backend.app.services.identity_resolution_service import IdentityResolutionService, identity_resolution_service

class FeedService:
    """
    Read side of the live plate feed. Every entry is a resolved observation keyed by
    observation id, so a refinement of the same source_event_id (which updates the
    same observation row) reaches clients as an update to the item they already hold.
    """

    def __init__(self, resolver: IdentityResolutionService = identity_resolution_service):
        self.resolver = resolver

    @staticmethod
    def current_cursor(db: Session) -> int:
        return db.query(func.max(ObservationFeedEvent.id)).scalar() or 0

    @staticmethod
    def _load_observations(db: Session, ids: Iterable[UUID]) -> List[ObservationEvent]:
        return (
            db.query(ObservationEvent)
            .options(selectinload(ObservationEvent.gate), selectinload(ObservationEvent.created_by))
            .filter(ObservationEvent.id.in_(list(ids)))
            .all()
        )

    def snapshot(self, db: Session, limit: int = 100) -> FeedPage:
        """Latest observations plus the cursor to stream from."""
        # Read the cursor first: anything committed afterwards is re-delivered by
        # changes_since(), and clients upsert by observation id.
        cursor = self.current_cursor(db)
        observations = (
            db.query(ObservationEvent)
            .options(selectinload(ObservationEvent.gate), selectinload(ObservationEvent.created_by))
            .order_by(ObservationEvent.observed_at.desc())
            .limit(limit)
            .all()
        )
        items = self.resolver.resolve_many(db, observations)
        return FeedPage(
            cursor=cursor,
            has_more=False,
            entries=[FeedEntry(kind="SNAPSHOT", cursor=cursor, item=item) for item in items],
        )

    def changes_since(self, db: Session, since_id: int, limit: int = 200) -> FeedPage:
        """Observations whose resolved view changed after since_id, one entry per observation."""
        events = (
            db.query(ObservationFeedEvent)
            .filter(ObservationFeedEvent.id > since_id)
            .order_by(ObservationFeedEvent.id.asc())
            .limit(limit + 1)
            .all()
        )
        has_more = len(events) > limit
        events = events[:limit]
        if not events:
            return FeedPage(cursor=since_id, has_more=False, entries=[])

        latest = {}
        for ev in events:
            latest[ev.observation_id] = ev
        ordered = sorted(latest.values(), key=lambda ev: ev.id)
        obs_by_id = {o.id: o for o in self._load_observations(db, latest.keys())}
        items = self.resolver.resolve_many(db, [obs_by_id[ev.observation_id] for ev in ordered])
        return FeedPage(
            cursor=events[-1].id,
            has_more=has_more,
            entries=[FeedEntry(kind=ev.kind.value, cursor=ev.id, item=item) for ev, item in zip(ordered, items)],
        )

feed_service = FeedService()
