"""add_recipient_brevo_purged_at

Date de suppression du contact dans Brevo après un rebond (anti-rappel
inutile de l'API Brevo à chaque passage du moteur d'emailing).

Revision ID: dd4e5f6purge8
Revises: cc3d4e5unsub7
Create Date: 2026-06-03 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "dd4e5f6purge8"
down_revision: Union[str, None] = "cc3d4e5unsub7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_campaign_recipients",
        sa.Column("brevo_purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_campaign_recipients", "brevo_purged_at")
