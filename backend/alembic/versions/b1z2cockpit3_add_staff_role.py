"""Add staff_role to users (business vs tech back-office cockpit)

Internal AORIA RH staff (role='admin') can be tagged 'business' or 'tech'
to decide which admin cockpit they land on and how the admin menu is
ordered. NULL = sees everything, lands on the business cockpit.

Revision ID: b1z2cockpit3
Revises: ff1a2b3fiches
Create Date: 2026-06-16

"""
from alembic import op
import sqlalchemy as sa

revision = "b1z2cockpit3"
down_revision = "ff1a2b3fiches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("staff_role", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "staff_role")
