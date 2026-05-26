"""add_sequence_step_branches

Revision ID: y0z1a2b3c4d5
Revises: x9y0z1a2b3c4
Create Date: 2026-05-26 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "y0z1a2b3c4d5"
down_revision: Union[str, None] = "x9y0z1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "email_sequence_steps",
        "template_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    op.create_table(
        "email_sequence_step_branches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("condition", sa.String(length=30), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["step_id"], ["email_sequence_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["email_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_step_branches_step_id",
        "email_sequence_step_branches",
        ["step_id"],
    )

    op.add_column(
        "email_campaign_events",
        sa.Column("branch_condition", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_campaign_events", "branch_condition")
    op.drop_index("ix_email_step_branches_step_id", table_name="email_sequence_step_branches")
    op.drop_table("email_sequence_step_branches")
    op.alter_column(
        "email_sequence_steps",
        "template_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
