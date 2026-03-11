"""add jurisprudence metadata columns to documents

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-03-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("juridiction", sa.String(100), nullable=True))
    op.add_column("documents", sa.Column("chambre", sa.String(100), nullable=True))
    op.add_column("documents", sa.Column("formation", sa.String(100), nullable=True))
    op.add_column("documents", sa.Column("numero_pourvoi", sa.String(50), nullable=True))
    op.add_column("documents", sa.Column("date_decision", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("solution", sa.String(50), nullable=True))
    op.add_column("documents", sa.Column("publication", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "publication")
    op.drop_column("documents", "solution")
    op.drop_column("documents", "date_decision")
    op.drop_column("documents", "numero_pourvoi")
    op.drop_column("documents", "formation")
    op.drop_column("documents", "chambre")
    op.drop_column("documents", "juridiction")
