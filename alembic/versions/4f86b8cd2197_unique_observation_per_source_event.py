"""unique observation per source event

Revision ID: 4f86b8cd2197
Revises: 4076a5142882
Create Date: 2026-10-13 23:31:12.405821

Audit 2026-10-13: (source, source_event_id) idempotency was check-then-insert over a non-unique
index, so concurrent ingestion of one Frigate event could store two observations for one passage.
ObservationService now serialises those writers with an advisory lock; this makes the database
refuse a second row for the same event. Rows without a source_event_id (MANUAL) are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f86b8cd2197'
down_revision: Union[str, Sequence[str], None] = '4076a5142882'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    duplicates = op.get_bind().execute(sa.text(
        "SELECT source, source_event_id, count(*) FROM observation_events "
        "WHERE source_event_id IS NOT NULL GROUP BY source, source_event_id HAVING count(*) > 1"
    )).all()
    if duplicates:
        raise RuntimeError(
            "Duplicate observations per source event must be merged by hand before this migration: "
            + "; ".join(f"{source}/{event_id} x{n}" for source, event_id, n in duplicates)
        )
    op.drop_index('ix_observation_events_source_event', table_name='observation_events')
    op.create_index(
        'ix_observation_events_source_event', 'observation_events', ['source', 'source_event_id'],
        unique=True, postgresql_where=sa.text('source_event_id IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_observation_events_source_event', table_name='observation_events')
    op.create_index('ix_observation_events_source_event', 'observation_events', ['source', 'source_event_id'], unique=False)
