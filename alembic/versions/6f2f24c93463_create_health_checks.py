"""create health_checks

Revision ID: 6f2f24c93463
Revises: 4f86b8cd2197
Create Date: 2026-10-13 23:48:40.119207

Audit 2026-10-13: HealthCheckRecord is in Base.metadata but no revision created its table, so on a
fresh database `alembic upgrade head` followed by `alembic check` failed ("Detected added table
'health_checks'"). Existing databases have the table because GET /health/db used to run
Base.metadata.create_all(); this revision creates it only where it is missing, with the same shape.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f2f24c93463'
down_revision: Union[str, Sequence[str], None] = '4f86b8cd2197'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if sa.inspect(op.get_bind()).has_table('health_checks'):
        return
    op.create_table('health_checks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('component', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_health_checks_id'), 'health_checks', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema. Leaves health_checks in place: on existing databases it predates this revision."""
    pass
