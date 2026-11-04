"""unique fiche per user and message

Revision ID: o4fiche01
Revises: n3session01
Create Date: 2026-11-04

Deux onglets pouvaient créer deux fiches pour le même message ; ensuite la
régénération plantait (MultipleResultsFound). On garde la fiche la plus récente
puis on pose la contrainte unique.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "o4fiche01"
down_revision: str | None = "n3session01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM fiches f
        USING fiches g
        WHERE f.message_id IS NOT NULL
          AND f.user_id = g.user_id
          AND f.message_id = g.message_id
          AND (f.updated_at, f.id) < (g.updated_at, g.id)
        """
    )
    op.create_unique_constraint("uq_fiches_user_message", "fiches", ["user_id", "message_id"])


def downgrade() -> None:
    op.drop_constraint("uq_fiches_user_message", "fiches", type_="unique")
