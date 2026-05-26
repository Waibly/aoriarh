"""add_template_preview_text

Revision ID: z1a2b3c4d5e6
Revises: y0z1a2b3c4d5
Create Date: 2026-05-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "z1a2b3c4d5e6"
down_revision: Union[str, None] = "y0z1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "email_templates",
        sa.Column("preview_text", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_templates", "preview_text")
