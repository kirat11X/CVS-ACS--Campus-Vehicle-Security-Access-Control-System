"""staging screening schema draft; do not place in alembic/versions or execute.

Revision ID: research_screening_draft
Revises: 1c9f9a684531 (confirmed from existing migration source)
Create Date: 2026-10-09 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "research_screening_draft"
down_revision: Union[str, None] = "1c9f9a684531"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

screening_action = postgresql.ENUM("ALLOW", "REVIEW", "ALERT", name="screening_action_enum")
screening_action_col = postgresql.ENUM("ALLOW", "REVIEW", "ALERT", name="screening_action_enum", create_type=False)


def upgrade() -> None:
    # Explicitly create enum type with checkfirst=True per context.md section 3F
    screening_action.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "item_categories",
        sa.Column("code", sa.String(50), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("default_action", screening_action_col, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_item_categories_active", "item_categories", ["active"])

    op.create_table(
        "screening_policy_rules",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("category_code", sa.String(50), nullable=False),
        sa.Column("action", screening_action_col, nullable=False),
        sa.Column("min_quantity", sa.Integer(), nullable=True),
        sa.Column("max_quantity", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(30), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["category_code"], ["item_categories.code"]),
    )
    op.create_index("ix_screening_policy_rules_category_code", "screening_policy_rules", ["category_code"])
    op.create_index("ix_screening_policy_rules_platform", "screening_policy_rules", ["platform"])
    op.create_index("ix_screening_policy_rules_policy_version", "screening_policy_rules", ["policy_version"])
    op.create_index("ix_screening_policy_rules_active", "screening_policy_rules", ["active"])

    op.create_table(
        "invoice_line_classifications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("invoice_item_id", sa.UUID(), nullable=False),
        sa.Column("category_code", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("classifier_name", sa.String(120), nullable=False),
        sa.Column("classifier_version", sa.String(120), nullable=False),
        sa.Column("normalized_item_text", sa.String(300), nullable=False),
        sa.Column("raw_item_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invoice_item_id"], ["invoice_items.id"]),
        sa.ForeignKeyConstraint(["category_code"], ["item_categories.code"]),
    )
    op.create_index("ix_invoice_line_classifications_invoice_item_id", "invoice_line_classifications", ["invoice_item_id"])
    op.create_index("ix_invoice_line_classifications_category_code", "invoice_line_classifications", ["category_code"])
    op.create_index("ix_invoice_line_classifications_created_at", "invoice_line_classifications", ["created_at"])

    op.create_table(
        "invoice_screening_results",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("outcome", screening_action_col, nullable=False),
        sa.Column("matched_rule_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("reason_codes", postgresql.ARRAY(sa.String(80)), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("security_alert_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["security_alert_id"], ["security_alerts.id"]),
    )
    op.create_index("ix_invoice_screening_results_invoice_id", "invoice_screening_results", ["invoice_id"])
    op.create_index("ix_invoice_screening_results_outcome", "invoice_screening_results", ["outcome"])
    op.create_index("ix_invoice_screening_results_security_alert_id", "invoice_screening_results", ["security_alert_id"])
    op.create_index("ix_invoice_screening_results_created_at", "invoice_screening_results", ["created_at"])

    op.create_table(
        "ml_eval_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("track", sa.String(20), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("model_version", sa.String(160), nullable=False),
        sa.Column("dataset_name", sa.String(160), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ml_eval_runs_track", "ml_eval_runs", ["track"])
    op.create_index("ix_ml_eval_runs_created_at", "ml_eval_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ml_eval_runs_created_at", table_name="ml_eval_runs")
    op.drop_index("ix_ml_eval_runs_track", table_name="ml_eval_runs")
    op.drop_table("ml_eval_runs")

    op.drop_index("ix_invoice_screening_results_created_at", table_name="invoice_screening_results")
    op.drop_index("ix_invoice_screening_results_security_alert_id", table_name="invoice_screening_results")
    op.drop_index("ix_invoice_screening_results_outcome", table_name="invoice_screening_results")
    op.drop_index("ix_invoice_screening_results_invoice_id", table_name="invoice_screening_results")
    op.drop_table("invoice_screening_results")

    op.drop_index("ix_invoice_line_classifications_created_at", table_name="invoice_line_classifications")
    op.drop_index("ix_invoice_line_classifications_category_code", table_name="invoice_line_classifications")
    op.drop_index("ix_invoice_line_classifications_invoice_item_id", table_name="invoice_line_classifications")
    op.drop_table("invoice_line_classifications")

    op.drop_index("ix_screening_policy_rules_active", table_name="screening_policy_rules")
    op.drop_index("ix_screening_policy_rules_policy_version", table_name="screening_policy_rules")
    op.drop_index("ix_screening_policy_rules_platform", table_name="screening_policy_rules")
    op.drop_index("ix_screening_policy_rules_category_code", table_name="screening_policy_rules")
    op.drop_table("screening_policy_rules")

    op.drop_index("ix_item_categories_active", table_name="item_categories")
    op.drop_table("item_categories")

    screening_action.drop(op.get_bind(), checkfirst=True)
