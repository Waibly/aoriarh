"""add ccn_reference and organisation_conventions tables

Revision ID: i4d5e6f7g8h9
Revises: h3c4d5e6f7g8
Create Date: 2026-03-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i4d5e6f7g8h9"
down_revision: str | None = "h3c4d5e6f7g8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CCN reference table (populated from KALI API)
    op.create_table(
        "ccn_reference",
        sa.Column("idcc", sa.String(4), nullable=False),
        sa.Column("titre", sa.Text(), nullable=False),
        sa.Column("titre_court", sa.String(255), nullable=True),
        sa.Column("kali_id", sa.String(30), nullable=True),
        sa.Column("etat", sa.String(30), nullable=True),
        sa.Column("last_api_check", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("idcc"),
    )

    # Organisation <-> CCN pivot table
    op.create_table(
        "organisation_conventions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("idcc", sa.String(4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("articles_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["idcc"], ["ccn_reference.idcc"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "idcc", name="uq_org_convention"),
    )
    op.create_index(
        "ix_organisation_conventions_organisation_id",
        "organisation_conventions",
        ["organisation_id"],
    )
    op.create_index(
        "ix_organisation_conventions_idcc",
        "organisation_conventions",
        ["idcc"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organisation_conventions_idcc",
        table_name="organisation_conventions",
    )
    op.drop_index(
        "ix_organisation_conventions_organisation_id",
        table_name="organisation_conventions",
    )
    op.drop_table("organisation_conventions")
    op.drop_table("ccn_reference")
