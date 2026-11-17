"""add_delivery_screening_and_decisions

Revision ID: c7a3e91d5f20
Revises: b5e9171d27fb
Create Date: 2026-10-20 12:00:00.000000

Phase 7 (delivery invoice screening):
  * enums screening_verdict_enum (ALLOW/REVIEW/ALERT), guard_decision_enum
    (CLEARED/HELD/ESCALATED), delivery_source_enum (LOCAL_INTAKE/WHATSAPP/CONSOLE),
    created explicitly (context.md 3F).
  * invoices: source, sender, gate_id, preview_path, ocr_engine, delivery_fee,
    computed_total, totals_match, overall_verdict, reply_text, created_by_id.
  * invoice_items: line_no, category, reason_code, verdict, confidence; quantity becomes
    nullable (OCR may not read it). Existing rows are untouched.
  * delivery_decisions: append-only guard decisions (row triggers + TRUNCATE trigger).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7a3e91d5f20'
down_revision: Union[str, Sequence[str], None] = 'b5e9171d27fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VERDICTS = ('ALLOW', 'REVIEW', 'ALERT')
DECISIONS = ('CLEARED', 'HELD', 'ESCALATED')
SOURCES = ('LOCAL_INTAKE', 'WHATSAPP', 'CONSOLE')


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Enum types, created explicitly (context.md 3F)
    sa.Enum(*VERDICTS, name='screening_verdict_enum').create(op.get_bind(), checkfirst=True)
    sa.Enum(*DECISIONS, name='guard_decision_enum').create(op.get_bind(), checkfirst=True)
    sa.Enum(*SOURCES, name='delivery_source_enum').create(op.get_bind(), checkfirst=True)
    verdict = postgresql.ENUM(*VERDICTS, name='screening_verdict_enum', create_type=False)

    # 2. Screening result per invoice submission
    op.add_column('invoices', sa.Column('source', postgresql.ENUM(*SOURCES, name='delivery_source_enum', create_type=False), nullable=True))
    op.add_column('invoices', sa.Column('sender', sa.String(length=50), nullable=True))
    op.add_column('invoices', sa.Column('gate_id', sa.String(length=30), nullable=True))
    op.add_column('invoices', sa.Column('preview_path', sa.String(length=255), nullable=True))
    op.add_column('invoices', sa.Column('ocr_engine', sa.String(length=30), nullable=True))
    op.add_column('invoices', sa.Column('delivery_fee', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('invoices', sa.Column('computed_total', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('invoices', sa.Column('totals_match', sa.Boolean(), nullable=True))
    op.add_column('invoices', sa.Column('overall_verdict', verdict, nullable=True))
    op.add_column('invoices', sa.Column('reply_text', sa.Text(), nullable=True))
    op.add_column('invoices', sa.Column('created_by_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_invoices_source'), 'invoices', ['source'], unique=False)
    op.create_index(op.f('ix_invoices_overall_verdict'), 'invoices', ['overall_verdict'], unique=False)
    op.create_foreign_key('invoices_gate_id_fkey', 'invoices', 'gates', ['gate_id'], ['id'])
    op.create_foreign_key('invoices_created_by_id_fkey', 'invoices', 'users', ['created_by_id'], ['id'])

    # 3. Screening per line
    op.add_column('invoice_items', sa.Column('line_no', sa.Integer(), nullable=True))
    op.add_column('invoice_items', sa.Column('category', sa.String(length=30), nullable=True))
    op.add_column('invoice_items', sa.Column('reason_code', sa.String(length=40), nullable=True))
    op.add_column('invoice_items', sa.Column('verdict', verdict, nullable=True))
    op.add_column('invoice_items', sa.Column('confidence', sa.Float(), nullable=True))
    op.alter_column('invoice_items', 'quantity', existing_type=sa.INTEGER(), nullable=True)

    # 4. Append-only guard decisions
    op.create_table('delivery_decisions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('invoice_id', sa.UUID(), nullable=False),
    sa.Column('decision', postgresql.ENUM(*DECISIONS, name='guard_decision_enum', create_type=False), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('decided_by_id', sa.UUID(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['decided_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
    sa.ForeignKeyConstraint(['order_id'], ['delivery_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_delivery_decisions_decided_at'), 'delivery_decisions', ['decided_at'], unique=False)
    op.create_index(op.f('ix_delivery_decisions_decided_by_id'), 'delivery_decisions', ['decided_by_id'], unique=False)
    op.create_index(op.f('ix_delivery_decisions_invoice_id'), 'delivery_decisions', ['invoice_id'], unique=False)
    op.create_index(op.f('ix_delivery_decisions_order_id'), 'delivery_decisions', ['order_id'], unique=False)
    op.execute("""
        CREATE FUNCTION delivery_decisions_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'delivery_decisions is append-only (% rejected)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER delivery_decisions_append_only
        BEFORE UPDATE OR DELETE ON delivery_decisions
        FOR EACH ROW EXECUTE FUNCTION delivery_decisions_append_only()
    """)
    # append_only_reject_truncate() comes from b5e9171d27fb
    op.execute("""
        CREATE TRIGGER delivery_decisions_reject_truncate
        BEFORE TRUNCATE ON delivery_decisions
        FOR EACH STATEMENT EXECUTE FUNCTION append_only_reject_truncate()
    """)


def downgrade() -> None:
    """Downgrade schema. Discards guard delivery decisions and the screening columns."""
    op.execute("DROP TRIGGER IF EXISTS delivery_decisions_reject_truncate ON delivery_decisions")
    op.execute("DROP TRIGGER IF EXISTS delivery_decisions_append_only ON delivery_decisions")
    op.execute("DROP FUNCTION IF EXISTS delivery_decisions_append_only()")
    op.drop_index(op.f('ix_delivery_decisions_order_id'), table_name='delivery_decisions')
    op.drop_index(op.f('ix_delivery_decisions_invoice_id'), table_name='delivery_decisions')
    op.drop_index(op.f('ix_delivery_decisions_decided_by_id'), table_name='delivery_decisions')
    op.drop_index(op.f('ix_delivery_decisions_decided_at'), table_name='delivery_decisions')
    op.drop_table('delivery_decisions')

    op.execute("UPDATE invoice_items SET quantity = 1 WHERE quantity IS NULL")
    op.alter_column('invoice_items', 'quantity', existing_type=sa.INTEGER(), nullable=False)
    for column in ('confidence', 'verdict', 'reason_code', 'category', 'line_no'):
        op.drop_column('invoice_items', column)

    op.drop_constraint('invoices_created_by_id_fkey', 'invoices', type_='foreignkey')
    op.drop_constraint('invoices_gate_id_fkey', 'invoices', type_='foreignkey')
    op.drop_index(op.f('ix_invoices_overall_verdict'), table_name='invoices')
    op.drop_index(op.f('ix_invoices_source'), table_name='invoices')
    for column in ('created_by_id', 'reply_text', 'overall_verdict', 'totals_match', 'computed_total',
                   'delivery_fee', 'ocr_engine', 'preview_path', 'gate_id', 'sender', 'source'):
        op.drop_column('invoices', column)

    sa.Enum(name='delivery_source_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='guard_decision_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='screening_verdict_enum').drop(op.get_bind(), checkfirst=True)
