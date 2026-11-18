"""add_gate_stream_settings

Revision ID: d91a27e491bc
Revises: ccf298e62015
Create Date: 2026-11-19 01:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd91a27e491bc'
down_revision: Union[str, Sequence[str], None] = 'ccf298e62015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create gate_stream_settings table and seed GATE_1, GATE_2, GATE_3 defaults."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS gate_stream_settings (
            gate_id VARCHAR(30) PRIMARY KEY REFERENCES gates(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ip_address VARCHAR(100) NOT NULL DEFAULT '192.168.1.100',
            port INTEGER NOT NULL DEFAULT 8080,
            protocol VARCHAR(10) NOT NULL DEFAULT 'http',
            stream_path VARCHAR(200) NOT NULL DEFAULT '/video',
            custom_url VARCHAR(500),
            total_fps_budget FLOAT NOT NULL DEFAULT 15.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Ensure GATE_1, GATE_2, GATE_3 exist before inserting settings
        INSERT INTO gates (id, name, location, status, direction_capability, created_at, updated_at)
        VALUES 
            ('GATE_1', 'Main North Gate', 'North Campus Entrance', 'ACTIVE', 'BIDIRECTIONAL', NOW(), NOW()),
            ('GATE_2', 'South Gate', 'South Campus Gate', 'ACTIVE', 'BIDIRECTIONAL', NOW(), NOW()),
            ('GATE_3', 'Hostel East Gate', 'East Hostel Road', 'ACTIVE', 'BIDIRECTIONAL', NOW(), NOW())
        ON CONFLICT (id) DO NOTHING;

        -- Seed default stream configs (GATE_1 enabled=TRUE, GATE_2 and GATE_3 enabled=FALSE)
        INSERT INTO gate_stream_settings (gate_id, enabled, ip_address, port, protocol, stream_path, total_fps_budget, created_at, updated_at)
        VALUES
            ('GATE_1', TRUE,  '192.168.1.100', 8080, 'http', '/video', 15.0, NOW(), NOW()),
            ('GATE_2', FALSE, '192.168.1.101', 8080, 'http', '/video', 15.0, NOW(), NOW()),
            ('GATE_3', FALSE, '192.168.1.102', 8080, 'http', '/video', 15.0, NOW(), NOW())
        ON CONFLICT (gate_id) DO NOTHING;
    """)


def downgrade() -> None:
    """Downgrade schema: drop gate_stream_settings table."""
    op.execute("""
        DROP TABLE IF EXISTS gate_stream_settings;
    """)
