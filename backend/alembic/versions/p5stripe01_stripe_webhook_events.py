"""stripe webhook events already processed

Revision ID: p5stripe01
Revises: o4fiche01
Create Date: 2026-11-04

Stripe redelivers events; we record processed ids so a redelivery does not
send a second e-mail or apply a state change twice.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p5stripe01"
down_revision: str | None = "o4fiche01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_events")
