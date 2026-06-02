"""add_email_unsubscribes

Liste de suppression des emails désinscrits (conformité RGPD).

Revision ID: cc3d4e5unsub7
Revises: bb2c3d4send6
Create Date: 2026-06-02 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cc3d4e5unsub7"
down_revision: Union[str, None] = "bb2c3d4send6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_unsubscribes",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("email"),
    )


def downgrade() -> None:
    op.drop_table("email_unsubscribes")
