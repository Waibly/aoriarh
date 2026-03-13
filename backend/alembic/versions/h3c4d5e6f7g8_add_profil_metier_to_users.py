"""add profil_metier to users

Revision ID: h3c4d5e6f7g8
Revises: g2b3c4d5e6f7
Create Date: 2026-03-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h3c4d5e6f7g8"
down_revision: str | None = "g2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("profil_metier", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "profil_metier")
