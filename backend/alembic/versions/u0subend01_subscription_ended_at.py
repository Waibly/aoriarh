"""Date de fin effective des abonnements (calcul du taux de résiliation)

``canceled_at`` est la date de la *demande* de résiliation. Pour une résiliation
en fin de période, l'abonnement s'arrête plus tard : sans date de fin effective,
le taux de résiliation à 30 jours manquait ces départs.

Revision ID: u0subend01
Revises: t9quality01
Create Date: 2026-11-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "u0subend01"
down_revision: str | None = "t9quality01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Abonnements déjà terminés : la dernière écriture de la ligne est celle du
    # passage à « canceled » (webhook de suppression ou annulation admin).
    op.execute(
        "UPDATE subscriptions SET ended_at = COALESCE(updated_at, canceled_at) "
        "WHERE status = 'canceled' AND ended_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "ended_at")
