"""add_campaign_waves

Découpage des campagnes en vagues : table email_campaign_waves + colonnes
wave_id / scheduled_at sur email_campaign_recipients.

Revision ID: aa1b2c3wave5
Revises: z1a2b3c4d5e6
Create Date: 2026-06-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "aa1b2c3wave5"
down_revision: Union[str, None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_campaign_waves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["email_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_campaign_waves_campaign",
        "email_campaign_waves",
        ["campaign_id"],
    )
    # Index pour le garde-fou « 300 mails / jour » : somme des vagues par date.
    op.create_index(
        "ix_email_campaign_waves_scheduled_at",
        "email_campaign_waves",
        ["scheduled_at"],
    )

    op.add_column(
        "email_campaign_recipients",
        sa.Column("wave_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "email_campaign_recipients",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_email_campaign_recipients_wave",
        "email_campaign_recipients",
        "email_campaign_waves",
        ["wave_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_email_campaign_recipients_wave",
        "email_campaign_recipients",
        type_="foreignkey",
    )
    op.drop_column("email_campaign_recipients", "scheduled_at")
    op.drop_column("email_campaign_recipients", "wave_id")
    op.drop_index("ix_email_campaign_waves_scheduled_at", table_name="email_campaign_waves")
    op.drop_index("ix_email_campaign_waves_campaign", table_name="email_campaign_waves")
    op.drop_table("email_campaign_waves")
