"""Widen solution column from varchar(50) to varchar(200).

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "documents",
        "solution",
        type_=sa.String(200),
        existing_type=sa.String(50),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "documents",
        "solution",
        type_=sa.String(50),
        existing_type=sa.String(200),
        existing_nullable=True,
    )
