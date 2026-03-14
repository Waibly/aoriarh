"""Add sync_logs table for automated sync history

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-03-14

"""

import sqlalchemy as sa
from alembic import op

revision = "l7m8n9o0p1q2"
down_revision = "k6l7m8n9o0p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sync_type", sa.String(30), nullable=False, index=True),
        sa.Column("idcc", sa.String(4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("items_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_created", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sync_logs")
