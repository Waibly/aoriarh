"""Replace messages.cost_usd snapshot by a question_id link to api_usage_logs

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-04-09

The cost_usd snapshot on messages was unreliable: only ~7% of messages had
it persisted (timing race + missing OOS branches). We replace it by a stable
link `messages.question_id` that points to the cost-tracker context_id used
in api_usage_logs. The cost is now always computed live via JOIN, and the
two admin pages (/admin/costs and /admin/quality) share the exact same
formula. Old messages keep NULL question_id and lose their per-message cost
display (still available globally via /admin/costs).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "s4t5u6v7w8x9"
down_revision = "r3s4t5u6v7w8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_messages_question_id", "messages", ["question_id"], unique=False
    )
    op.drop_column("messages", "cost_usd")


def downgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
    )
    op.drop_index("ix_messages_question_id", table_name="messages")
    op.drop_column("messages", "question_id")
