"""Add use_custom to organisation_conventions

Revision ID: n9o0p1q2r3s4
Revises: m8n9o0p1q2r3
Create Date: 2026-03-16

"""

import sqlalchemy as sa
from alembic import op

revision = "n9o0p1q2r3s4"
down_revision = "m8n9o0p1q2r3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_conventions",
        sa.Column("use_custom", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("organisation_conventions", "use_custom")
