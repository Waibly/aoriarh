"""Add hidden_at column to conversations for soft-delete

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-04-09

Soft-delete column for conversations. The chat sidebar needs a way to
hide conversations from the user without destroying the underlying
messages, which are still required for analytics (cost tracking,
quality metrics, audit logs).
"""

import sqlalchemy as sa
from alembic import op

revision = "r3s4t5u6v7w8"
down_revision = "q2r3s4t5u6v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "hidden_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversations_hidden_at",
        "conversations",
        ["hidden_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_hidden_at", table_name="conversations")
    op.drop_column("conversations", "hidden_at")
