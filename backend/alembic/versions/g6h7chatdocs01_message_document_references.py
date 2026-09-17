"""Explicit versioned document references per user message.

Revision ID: g6h7chatdocs01
Revises: f5g6docops01
"""
import sqlalchemy as sa
from alembic import op

revision = "g6h7chatdocs01"
down_revision = "f5g6docops01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("document_references", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("messages", "document_references")
