"""add convention_collective and secteur_activite to organisations

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g2b3c4d5e6f7"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organisations", sa.Column("convention_collective", sa.String(255), nullable=True))
    op.add_column("organisations", sa.Column("secteur_activite", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("organisations", "secteur_activite")
    op.drop_column("organisations", "convention_collective")
