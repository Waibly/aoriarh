"""Add bocc_issues table

Revision ID: o0p1q2r3s4t5
Revises: n9o0p1q2r3s4
Create Date: 2026-03-16

"""

import sqlalchemy as sa
from alembic import op

revision = "o0p1q2r3s4t5"
down_revision = "n9o0p1q2r3s4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bocc_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("numero", sa.String(10), nullable=False, unique=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("avenants_count", sa.Integer(), server_default="0"),
        sa.Column("avenants_ingested", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(20), server_default="processed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("bocc_issues")
