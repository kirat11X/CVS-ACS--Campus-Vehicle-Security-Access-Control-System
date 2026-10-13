"""add_observation_events_and_gate_status

Revision ID: 1c9f9a684531
Revises: 9e13fe119fc4
Create Date: 2026-09-22 03:12:20.355423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1c9f9a684531'
down_revision: Union[str, Sequence[str], None] = '9e13fe119fc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add INACTIVE to existing gate_status_enum
    op.execute("ALTER TYPE gate_status_enum ADD VALUE IF NOT EXISTS 'INACTIVE'")

    # 2. Create enum types in PostgreSQL
    op.execute("CREATE TYPE observation_source_enum AS ENUM ('FRIGATE', 'MANUAL', 'OTHER')")
    op.execute("CREATE TYPE observed_vehicle_type_enum AS ENUM ('CAR', 'MOTORCYCLE', 'BUS', 'TRUCK', 'BICYCLE', 'UNKNOWN')")
    op.execute("CREATE TYPE observation_direction_enum AS ENUM ('ENTRY', 'EXIT', 'UNKNOWN')")

    # 3. Create observation_events table using existing types
    op.create_table('observation_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('gate_id', sa.String(length=30), nullable=False),
    sa.Column('camera_id', sa.String(length=50), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', postgresql.ENUM('FRIGATE', 'MANUAL', 'OTHER', name='observation_source_enum', create_type=False), nullable=False),
    sa.Column('source_event_id', sa.String(length=100), nullable=True),
    sa.Column('raw_plate', sa.String(length=30), nullable=True),
    sa.Column('normalized_plate', sa.String(length=30), nullable=True),
    sa.Column('plate_confidence', sa.Float(), nullable=True),
    sa.Column('vehicle_type', postgresql.ENUM('CAR', 'MOTORCYCLE', 'BUS', 'TRUCK', 'BICYCLE', 'UNKNOWN', name='observed_vehicle_type_enum', create_type=False), nullable=False),
    sa.Column('vehicle_confidence', sa.Float(), nullable=True),
    sa.Column('direction', postgresql.ENUM('ENTRY', 'EXIT', 'UNKNOWN', name='observation_direction_enum', create_type=False), nullable=False),
    sa.Column('metadata_payload', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['gate_id'], ['gates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_observation_events_gate_id'), 'observation_events', ['gate_id'], unique=False)
    op.create_index(op.f('ix_observation_events_normalized_plate'), 'observation_events', ['normalized_plate'], unique=False)
    op.create_index(op.f('ix_observation_events_observed_at'), 'observation_events', ['observed_at'], unique=False)
    op.create_index('ix_observation_events_source_event', 'observation_events', ['source', 'source_event_id'], unique=False)
    op.create_index(op.f('ix_observation_events_source_event_id'), 'observation_events', ['source_event_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_observation_events_source_event_id'), table_name='observation_events')
    op.drop_index('ix_observation_events_source_event', table_name='observation_events')
    op.drop_index(op.f('ix_observation_events_observed_at'), table_name='observation_events')
    op.drop_index(op.f('ix_observation_events_normalized_plate'), table_name='observation_events')
    op.drop_index(op.f('ix_observation_events_gate_id'), table_name='observation_events')
    op.drop_table('observation_events')

    op.execute("DROP TYPE IF EXISTS observation_direction_enum")
    op.execute("DROP TYPE IF EXISTS observed_vehicle_type_enum")
    op.execute("DROP TYPE IF EXISTS observation_source_enum")
