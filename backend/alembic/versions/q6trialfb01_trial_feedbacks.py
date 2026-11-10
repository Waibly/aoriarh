"""trial_feedbacks : réponses au questionnaire de fin d'essai

Revision ID: q6trialfb01
Revises: p5stripe01
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "q6trialfb01"
down_revision: str | None = "p5stripe01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trial_feedbacks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("questions_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trial_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trial_feedbacks_account_id", "trial_feedbacks", ["account_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trial_feedbacks_account_id", table_name="trial_feedbacks")
    op.drop_table("trial_feedbacks")
