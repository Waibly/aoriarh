"""Add rag_trace, cost_usd, latency_ms to messages + GIN full-text index

Revision ID: p1q2r3s4t5u6
Revises: o0p1q2r3s4t5
Create Date: 2026-04-07

Adds the columns needed by the admin Quality page to inspect a question
in detail (full RAG pipeline trace) and to compute KPIs (latency, cost
per question). Also adds a French full-text search index on message
content for the conversation explorer search box.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p1q2r3s4t5u6"
down_revision = "o0p1q2r3s4t5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. New columns on messages
    # JSONB in Postgres for efficient querying. The model uses a JSON+variant
    # so SQLite (used in tests) maps to TEXT automatically.
    op.add_column(
        "messages",
        sa.Column("rag_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )

    # 2. French full-text search index on messages.content
    # We use a GIN index on to_tsvector('french', content) for fast LIKE-style
    # search in the admin Quality conversation explorer.
    op.execute(
        "CREATE INDEX ix_messages_content_fts "
        "ON messages USING gin (to_tsvector('french', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_content_fts")
    op.drop_column("messages", "latency_ms")
    op.drop_column("messages", "cost_usd")
    op.drop_column("messages", "rag_trace")
