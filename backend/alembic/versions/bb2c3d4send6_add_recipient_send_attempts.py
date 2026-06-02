"""add_recipient_send_attempts

Compteur d'échecs d'envoi par destinataire (anti-retry infini).

Revision ID: bb2c3d4send6
Revises: aa1b2c3wave5
Create Date: 2026-06-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bb2c3d4send6"
down_revision: Union[str, None] = "aa1b2c3wave5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_campaign_recipients",
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("email_campaign_recipients", "send_attempts")
