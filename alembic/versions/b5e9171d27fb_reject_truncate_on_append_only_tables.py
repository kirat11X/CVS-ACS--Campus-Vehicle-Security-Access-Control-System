"""reject truncate on append-only tables

Revision ID: b5e9171d27fb
Revises: 6f2f24c93463
Create Date: 2026-10-14 00:12:31.508372

Audit 2026-10-13: observation_resolutions, vehicle_link_events and movement records in
entry_exit_logs were append-only through row-level BEFORE UPDATE OR DELETE triggers. Row triggers
do not fire for TRUNCATE, so one statement erased the whole history. Statement-level BEFORE
TRUNCATE triggers close that path; PostgreSQL fires them for tables reached through CASCADE too.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b5e9171d27fb'
down_revision: Union[str, Sequence[str], None] = '6f2f24c93463'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('observation_resolutions', 'vehicle_link_events', 'entry_exit_logs')


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE FUNCTION append_only_reject_truncate() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only (TRUNCATE rejected)', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_reject_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION append_only_reject_truncate()
        """)


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_truncate ON {table}")
    op.execute("DROP FUNCTION IF EXISTS append_only_reject_truncate()")
