"""Durable object storage intents, additive and without automatic cleanup.

Revision ID: f5g6docops01
Revises: e4f5docread01
"""
import sqlalchemy as sa
from alembic import op

revision = "f5g6docops01"
down_revision = "e4f5docread01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "storage_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("target_path", sa.String(1000), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_path"),
    )
    op.create_index("ix_storage_operations_document_id", "storage_operations", ["document_id"])
    op.create_index("ix_storage_operations_status", "storage_operations", ["status"])


def downgrade():
    # Resolve/export pending operations before downgrading; no bucket deletion here.
    op.drop_table("storage_operations")
