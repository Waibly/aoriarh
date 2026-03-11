"""add chunk_count and indexation_error to documents

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-02-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column(
        "documents", sa.Column("indexation_error", sa.String(500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "indexation_error")
    op.drop_column("documents", "chunk_count")
