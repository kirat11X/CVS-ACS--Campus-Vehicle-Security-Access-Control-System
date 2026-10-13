from datetime import timedelta
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import FEED_REGISTRY_LOOKBACK_HOURS
from backend.app.models.base import utc_now
from backend.app.models.enums import FeedEventKind
from backend.app.models.observation import ObservationEvent, ObservationFeedEvent

# Transaction-scoped advisory lock serialising feed-event inserts. Ids are drawn
# while the lock is held and the lock is released at commit, so ids become visible
# in increasing order and a reader's `id > cursor` query can never skip a row
# that commits late.
FEED_EVENT_LOCK_KEY = 5_031_602

def record_feed_event(db: Session, observation_id: UUID, kind: FeedEventKind) -> None:
    """Appends a feed change-log row in the caller's transaction (caller commits)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": FEED_EVENT_LOCK_KEY})
    db.add(ObservationFeedEvent(observation_id=observation_id, kind=kind))

def record_registry_update(db: Session, normalized_plate: str, limit: int = 50) -> int:
    """
    A registry change for a plate alters the linkage of recent observations of that
    plate; queue them for re-emission on the feed. Returns the number queued.
    """
    if not normalized_plate:
        return 0
    cutoff = utc_now() - timedelta(hours=FEED_REGISTRY_LOOKBACK_HOURS)
    rows = (
        db.query(ObservationEvent.id)
        .filter(ObservationEvent.normalized_plate == normalized_plate, ObservationEvent.observed_at >= cutoff)
        .order_by(ObservationEvent.observed_at.desc())
        .limit(limit)
        .all()
    )
    for (obs_id,) in rows:
        record_feed_event(db, obs_id, FeedEventKind.REGISTRY_UPDATED)
    return len(rows)
