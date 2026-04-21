"""Add hard_warning_email_sent_at to monthly_question_usage

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-04-21

Tracks whether we already sent the "you've used more than 120 % of your
monthly question quota" upsell email for a given billing period. Used
by BillingService.increment_question_count to avoid sending the same
email several times for one period.
"""

import sqlalchemy as sa
from alembic import op

revision = "u6v7w8x9y0z1"
down_revision = "t5u6v7w8x9y0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monthly_question_usage",
        sa.Column(
            "hard_warning_email_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("monthly_question_usage", "hard_warning_email_sent_at")
