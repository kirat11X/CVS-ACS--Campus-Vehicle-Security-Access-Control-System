"""one live gate per camera

Revision ID: 4076a5142882
Revises: 0453af6c03f6
Create Date: 2026-10-13 23:06:54.270078

Audit 2026-10-13: gates.camera_id was not unique, so two gates could claim one Frigate camera
and FrigateEventParser credited its events to whichever row PostgreSQL returned first. A camera
may now belong to at most one gate that is not INACTIVE; retired gates keep their old camera id
for the record (the development database has 12 INACTIVE gates on 'temp_cam').
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4076a5142882'
down_revision: Union[str, Sequence[str], None] = '0453af6c03f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    shared = op.get_bind().execute(sa.text(
        "SELECT camera_id, string_agg(id, ', ' ORDER BY id) FROM gates "
        "WHERE camera_id IS NOT NULL AND status <> 'INACTIVE' GROUP BY camera_id HAVING count(*) > 1"
    )).all()
    if shared:
        raise RuntimeError(
            "Cannot enforce one live gate per camera; deactivate or re-map these gates first: "
            + "; ".join(f"{camera}: {gates}" for camera, gates in shared)
        )
    op.create_index(
        'uq_gates_live_camera_id', 'gates', ['camera_id'], unique=True,
        postgresql_where=sa.text("camera_id IS NOT NULL AND status <> 'INACTIVE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_gates_live_camera_id', table_name='gates')
