"""Track refresh-token successors so concurrent refreshes are not treated as theft.

Revision ID: n3session01
Revises: m2security01
"""

from alembic import op
import sqlalchemy as sa

revision = "n3session01"
down_revision = "m2security01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("replaced_by_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_sessions", "replaced_by_id")
