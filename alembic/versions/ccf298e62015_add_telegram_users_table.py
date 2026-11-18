"""add_telegram_users_table

Revision ID: ccf298e62015
Revises: c7a3e91d5f20
Create Date: 2026-11-18 21:14:45.244947

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccf298e62015'
down_revision: Union[str, Sequence[str], None] = 'c7a3e91d5f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS telegram_users (
            chat_id BIGINT PRIMARY KEY,
            user_id BIGINT,
            username VARCHAR(100),
            full_name VARCHAR(100) NOT NULL,
            identifier VARCHAR(50) NOT NULL,
            location VARCHAR(150) NOT NULL,
            visit_count INTEGER DEFAULT 1 NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_telegram_users_identifier ON telegram_users(identifier);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        DROP INDEX IF EXISTS ix_telegram_users_identifier;
        DROP TABLE IF EXISTS telegram_users;
    """)
