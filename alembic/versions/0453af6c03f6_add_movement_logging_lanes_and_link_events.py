"""add_movement_logging_lanes_and_link_events

Revision ID: 0453af6c03f6
Revises: d529411fb6a3
Create Date: 2026-10-09 16:05:00.000000

Phase 6:
  * camera_lanes: administrator-declared lane role per camera (+ zone order for BIDIRECTIONAL).
  * entry_exit_logs: movement provenance columns (observation_id, correction_of_id,
    direction_method, direction_confidence, direction_evidence, plate_source,
    created_by_id, note). plate/normalized_plate/confidence/decision/reason_code become
    nullable: a movement record can lack a plate and never carries an access decision.
    Movement records (direction_method IS NOT NULL) are append-only via trigger.
  * vehicle_link_events: append-only human assertions linking a vehicle to an owner.
  * feed_event_kind_enum: + 'MOVEMENT_UPDATED'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0453af6c03f6'
down_revision: Union[str, Sequence[str], None] = 'd529411fb6a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LANE_ROLES = ('ENTRY_LANE', 'EXIT_LANE', 'BIDIRECTIONAL')
DIRECTION_METHODS = ('CAMERA_ROLE', 'ZONE_ORDER', 'GUARD_CONFIRMED', 'NONE')
PLATE_SOURCES = ('OBSERVATION', 'GUARD_CORRECTION')
LINK_METHODS = ('GUARD_VERIFIED_ID', 'ADMIN')


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Enum types, created explicitly (context.md 3F)
    op.execute("ALTER TYPE feed_event_kind_enum ADD VALUE IF NOT EXISTS 'MOVEMENT_UPDATED'")
    sa.Enum(*LANE_ROLES, name='lane_role_enum').create(op.get_bind(), checkfirst=True)
    sa.Enum(*DIRECTION_METHODS, name='direction_method_enum').create(op.get_bind(), checkfirst=True)
    sa.Enum(*PLATE_SOURCES, name='log_plate_source_enum').create(op.get_bind(), checkfirst=True)
    sa.Enum(*LINK_METHODS, name='link_method_enum').create(op.get_bind(), checkfirst=True)

    # 2. Lane configuration
    op.create_table('camera_lanes',
    sa.Column('camera_id', sa.String(length=50), nullable=False),
    sa.Column('gate_id', sa.String(length=30), nullable=False),
    sa.Column('lane_role', postgresql.ENUM(*LANE_ROLES, name='lane_role_enum', create_type=False), nullable=False),
    sa.Column('outside_zone', sa.String(length=64), nullable=True),
    sa.Column('inside_zone', sa.String(length=64), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('updated_by_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['gate_id'], ['gates.id'], ),
    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('camera_id')
    )
    op.create_index(op.f('ix_camera_lanes_gate_id'), 'camera_lanes', ['gate_id'], unique=False)

    # 3. Append-only vehicle link events
    op.create_table('vehicle_link_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('vehicle_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('method', postgresql.ENUM(*LINK_METHODS, name='link_method_enum', create_type=False), nullable=False),
    sa.Column('evidence_note', sa.Text(), nullable=False),
    sa.Column('linked_by_id', sa.UUID(), nullable=False),
    sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['linked_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['vehicle_owners.id'], ),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vehicle_link_events_linked_at'), 'vehicle_link_events', ['linked_at'], unique=False)
    op.create_index(op.f('ix_vehicle_link_events_linked_by_id'), 'vehicle_link_events', ['linked_by_id'], unique=False)
    op.create_index(op.f('ix_vehicle_link_events_owner_id'), 'vehicle_link_events', ['owner_id'], unique=False)
    op.create_index(op.f('ix_vehicle_link_events_vehicle_id'), 'vehicle_link_events', ['vehicle_id'], unique=False)
    op.execute("""
        CREATE FUNCTION vehicle_link_events_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'vehicle_link_events is append-only (% rejected)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER vehicle_link_events_append_only
        BEFORE UPDATE OR DELETE ON vehicle_link_events
        FOR EACH ROW EXECUTE FUNCTION vehicle_link_events_append_only()
    """)

    # 4. Movement provenance on entry_exit_logs
    op.add_column('entry_exit_logs', sa.Column('observation_id', sa.UUID(), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('correction_of_id', sa.UUID(), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('direction_method', postgresql.ENUM(*DIRECTION_METHODS, name='direction_method_enum', create_type=False), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('direction_confidence', sa.Float(), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('direction_evidence', sa.JSON(), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('plate_source', postgresql.ENUM(*PLATE_SOURCES, name='log_plate_source_enum', create_type=False), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('created_by_id', sa.UUID(), nullable=True))
    op.add_column('entry_exit_logs', sa.Column('note', sa.Text(), nullable=True))
    for column, existing_type in (
        ('plate', sa.VARCHAR(length=30)),
        ('normalized_plate', sa.VARCHAR(length=30)),
        ('confidence', sa.DOUBLE_PRECISION(precision=53)),
        ('decision', postgresql.ENUM('ALLOWED', 'DENIED', 'REVIEW', 'EXPIRED', name='log_access_state_enum', create_type=False)),
        ('reason_code', sa.VARCHAR(length=50)),
    ):
        op.alter_column('entry_exit_logs', column, existing_type=existing_type, nullable=True)
    op.create_index(op.f('ix_entry_exit_logs_correction_of_id'), 'entry_exit_logs', ['correction_of_id'], unique=False)
    op.create_index(op.f('ix_entry_exit_logs_created_by_id'), 'entry_exit_logs', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_entry_exit_logs_direction_method'), 'entry_exit_logs', ['direction_method'], unique=False)
    op.create_unique_constraint('entry_exit_logs_observation_id_key', 'entry_exit_logs', ['observation_id'])
    op.create_foreign_key('entry_exit_logs_observation_id_fkey', 'entry_exit_logs', 'observation_events', ['observation_id'], ['id'])
    op.create_foreign_key('entry_exit_logs_correction_of_id_fkey', 'entry_exit_logs', 'entry_exit_logs', ['correction_of_id'], ['id'])
    op.create_foreign_key('entry_exit_logs_created_by_id_fkey', 'entry_exit_logs', 'users', ['created_by_id'], ['id'])

    # Phase 6 movement records are append-only; legacy pre-Phase-6 rows keep their old behaviour.
    op.execute("""
        CREATE FUNCTION entry_exit_logs_movement_append_only() RETURNS trigger AS $$
        BEGIN
            IF OLD.direction_method IS NOT NULL THEN
                RAISE EXCEPTION 'movement records in entry_exit_logs are append-only (% rejected)', TG_OP;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER entry_exit_logs_movement_append_only
        BEFORE UPDATE OR DELETE ON entry_exit_logs
        FOR EACH ROW EXECUTE FUNCTION entry_exit_logs_movement_append_only()
    """)


def downgrade() -> None:
    """Downgrade schema. Discards Phase 6 movement records (they cannot satisfy the old NOT NULL columns)."""
    op.execute("DROP TRIGGER IF EXISTS entry_exit_logs_movement_append_only ON entry_exit_logs")
    op.execute("DROP FUNCTION IF EXISTS entry_exit_logs_movement_append_only()")
    op.execute("DELETE FROM entry_exit_logs WHERE correction_of_id IS NOT NULL")
    op.execute("DELETE FROM entry_exit_logs WHERE direction_method IS NOT NULL")

    op.drop_constraint('entry_exit_logs_created_by_id_fkey', 'entry_exit_logs', type_='foreignkey')
    op.drop_constraint('entry_exit_logs_correction_of_id_fkey', 'entry_exit_logs', type_='foreignkey')
    op.drop_constraint('entry_exit_logs_observation_id_fkey', 'entry_exit_logs', type_='foreignkey')
    op.drop_constraint('entry_exit_logs_observation_id_key', 'entry_exit_logs', type_='unique')
    op.drop_index(op.f('ix_entry_exit_logs_direction_method'), table_name='entry_exit_logs')
    op.drop_index(op.f('ix_entry_exit_logs_created_by_id'), table_name='entry_exit_logs')
    op.drop_index(op.f('ix_entry_exit_logs_correction_of_id'), table_name='entry_exit_logs')
    for column, existing_type in (
        ('reason_code', sa.VARCHAR(length=50)),
        ('decision', postgresql.ENUM('ALLOWED', 'DENIED', 'REVIEW', 'EXPIRED', name='log_access_state_enum', create_type=False)),
        ('confidence', sa.DOUBLE_PRECISION(precision=53)),
        ('normalized_plate', sa.VARCHAR(length=30)),
        ('plate', sa.VARCHAR(length=30)),
    ):
        op.alter_column('entry_exit_logs', column, existing_type=existing_type, nullable=False)
    for column in ('note', 'created_by_id', 'plate_source', 'direction_evidence', 'direction_confidence',
                   'direction_method', 'correction_of_id', 'observation_id'):
        op.drop_column('entry_exit_logs', column)

    op.execute("DROP TRIGGER IF EXISTS vehicle_link_events_append_only ON vehicle_link_events")
    op.execute("DROP FUNCTION IF EXISTS vehicle_link_events_append_only()")
    op.drop_index(op.f('ix_vehicle_link_events_vehicle_id'), table_name='vehicle_link_events')
    op.drop_index(op.f('ix_vehicle_link_events_owner_id'), table_name='vehicle_link_events')
    op.drop_index(op.f('ix_vehicle_link_events_linked_by_id'), table_name='vehicle_link_events')
    op.drop_index(op.f('ix_vehicle_link_events_linked_at'), table_name='vehicle_link_events')
    op.drop_table('vehicle_link_events')
    op.drop_index(op.f('ix_camera_lanes_gate_id'), table_name='camera_lanes')
    op.drop_table('camera_lanes')

    sa.Enum(name='link_method_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='log_plate_source_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='direction_method_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='lane_role_enum').drop(op.get_bind(), checkfirst=True)
    # 'MOVEMENT_UPDATED' stays in feed_event_kind_enum: PostgreSQL cannot drop enum values.
    op.execute("DELETE FROM observation_feed_events WHERE kind = 'MOVEMENT_UPDATED'")
