"""Add source_date to organisation_conventions

Revision ID: m8n9o0p1q2r3
Revises: l7m8n9o0p1q2
Create Date: 2026-03-16

"""

import sqlalchemy as sa
from alembic import op

revision = "m8n9o0p1q2r3"
down_revision = "l7m8n9o0p1q2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_conventions",
        sa.Column("source_date", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organisation_conventions", "source_date")
