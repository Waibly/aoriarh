"""organisations.territoire : lieu d'implantation (métropole, Alsace-Moselle, outre-mer)

Revision ID: r7territ01
Revises: q6trialfb01
Create Date: 2026-11-10 15:00:00.000000

Toutes les organisations existantes passent en « metropole » via le défaut
serveur. Les exceptions connues (ex. Cilam → la_reunion) se règlent à la main
après migration, pas ici.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r7territ01"
down_revision: str | None = "q6trialfb01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column(
            "territoire",
            sa.String(length=40),
            nullable=False,
            server_default="metropole",
        ),
    )


def downgrade() -> None:
    op.drop_column("organisations", "territoire")
