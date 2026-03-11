"""add_indexation_duration_ms

Revision ID: a1b2c3d4e5f6
Revises: dd744f0db6d3
Create Date: 2026-02-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'dd744f0db6d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("indexation_duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "indexation_duration_ms")
