"""add_manual_observations_guard_resolutions_and_feed

Revision ID: d529411fb6a3
Revises: 1c9f9a684531
Create Date: 2026-10-09 15:38:55.422802

Phase 5C:
  * observation_source_enum: ensure 'MANUAL' (already created by 1c9f9a684531; idempotent).
  * observation_events.created_by_id / note for guard-entered MANUAL observations.
  * vehicles.created_by_id / vehicle_owners.created_by_id for registration provenance.
  * observation_resolutions: append-only guard confirmations (UPDATE/DELETE blocked by trigger).
  * observation_feed_events: monotonic change log behind GET /feed and GET /feed/stream.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd529411fb6a3'
down_revision: Union[str, Sequence[str], None] = '1c9f9a684531'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESOLUTION_OUTCOMES = ('VEHICLE_CONFIRMED', 'NONE_OF_THESE')
FEED_EVENT_KINDS = ('OBSERVATION_CREATED', 'OBSERVATION_UPDATED', 'RESOLUTION_ADDED', 'REGISTRY_UPDATED')


def upgrade() -> None:
    """Upgrade schema."""
    # 1. MANUAL observation source (no-op where 1c9f9a684531 already created it)
    op.execute("ALTER TYPE observation_source_enum ADD VALUE IF NOT EXISTS 'MANUAL'")

    # 2. New enum types, created explicitly (context.md 3F)
    sa.Enum(*RESOLUTION_OUTCOMES, name='resolution_outcome_enum').create(op.get_bind(), checkfirst=True)
    sa.Enum(*FEED_EVENT_KINDS, name='feed_event_kind_enum').create(op.get_bind(), checkfirst=True)

    # 3. Provenance columns
    op.add_column('observation_events', sa.Column('created_by_id', sa.UUID(), nullable=True))
    op.add_column('observation_events', sa.Column('note', sa.Text(), nullable=True))
    op.create_index(op.f('ix_observation_events_created_by_id'), 'observation_events', ['created_by_id'], unique=False)
    op.create_foreign_key('observation_events_created_by_id_fkey', 'observation_events', 'users', ['created_by_id'], ['id'])

    op.add_column('vehicle_owners', sa.Column('created_by_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_vehicle_owners_created_by_id'), 'vehicle_owners', ['created_by_id'], unique=False)
    op.create_foreign_key('vehicle_owners_created_by_id_fkey', 'vehicle_owners', 'users', ['created_by_id'], ['id'])

    op.add_column('vehicles', sa.Column('created_by_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_vehicles_created_by_id'), 'vehicles', ['created_by_id'], unique=False)
    op.create_foreign_key('vehicles_created_by_id_fkey', 'vehicles', 'users', ['created_by_id'], ['id'])

    # 4. Append-only guard resolutions
    op.create_table('observation_resolutions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('observation_id', sa.UUID(), nullable=False),
    sa.Column('outcome', postgresql.ENUM(*RESOLUTION_OUTCOMES, name='resolution_outcome_enum', create_type=False), nullable=False),
    sa.Column('chosen_vehicle_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(outcome = 'VEHICLE_CONFIRMED') = (chosen_vehicle_id IS NOT NULL)", name='ck_observation_resolutions_outcome_vehicle'),
    sa.ForeignKeyConstraint(['chosen_vehicle_id'], ['vehicles.id'], ),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['observation_id'], ['observation_events.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_observation_resolutions_chosen_vehicle_id'), 'observation_resolutions', ['chosen_vehicle_id'], unique=False)
    op.create_index(op.f('ix_observation_resolutions_created_at'), 'observation_resolutions', ['created_at'], unique=False)
    op.create_index(op.f('ix_observation_resolutions_created_by_id'), 'observation_resolutions', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_observation_resolutions_observation_id'), 'observation_resolutions', ['observation_id'], unique=False)

    op.execute("""
        CREATE FUNCTION observation_resolutions_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'observation_resolutions is append-only (% rejected)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER observation_resolutions_append_only
        BEFORE UPDATE OR DELETE ON observation_resolutions
        FOR EACH ROW EXECUTE FUNCTION observation_resolutions_append_only()
    """)

    # 5. Live feed change log
    op.create_table('observation_feed_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('observation_id', sa.UUID(), nullable=False),
    sa.Column('kind', postgresql.ENUM(*FEED_EVENT_KINDS, name='feed_event_kind_enum', create_type=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['observation_id'], ['observation_events.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_observation_feed_events_observation_id'), 'observation_feed_events', ['observation_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_observation_feed_events_observation_id'), table_name='observation_feed_events')
    op.drop_table('observation_feed_events')

    op.execute("DROP TRIGGER IF EXISTS observation_resolutions_append_only ON observation_resolutions")
    op.execute("DROP FUNCTION IF EXISTS observation_resolutions_append_only()")
    op.drop_index(op.f('ix_observation_resolutions_observation_id'), table_name='observation_resolutions')
    op.drop_index(op.f('ix_observation_resolutions_created_by_id'), table_name='observation_resolutions')
    op.drop_index(op.f('ix_observation_resolutions_created_at'), table_name='observation_resolutions')
    op.drop_index(op.f('ix_observation_resolutions_chosen_vehicle_id'), table_name='observation_resolutions')
    op.drop_table('observation_resolutions')

    op.drop_constraint('vehicles_created_by_id_fkey', 'vehicles', type_='foreignkey')
    op.drop_index(op.f('ix_vehicles_created_by_id'), table_name='vehicles')
    op.drop_column('vehicles', 'created_by_id')

    op.drop_constraint('vehicle_owners_created_by_id_fkey', 'vehicle_owners', type_='foreignkey')
    op.drop_index(op.f('ix_vehicle_owners_created_by_id'), table_name='vehicle_owners')
    op.drop_column('vehicle_owners', 'created_by_id')

    op.drop_constraint('observation_events_created_by_id_fkey', 'observation_events', type_='foreignkey')
    op.drop_index(op.f('ix_observation_events_created_by_id'), table_name='observation_events')
    op.drop_column('observation_events', 'note')
    op.drop_column('observation_events', 'created_by_id')

    sa.Enum(name='feed_event_kind_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='resolution_outcome_enum').drop(op.get_bind(), checkfirst=True)
    # 'MANUAL' stays in observation_source_enum: PostgreSQL cannot drop enum values,
    # and the value predates this revision (created by 1c9f9a684531).
