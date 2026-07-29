"""Add marketing attribution fields to users (utm, gclid, referrer, landing page)

Captured on the marketing site at first visit, forwarded at signup. This is
our primary source of truth for "signups by campaign" — the Google consoles
are only a secondary steering view.

Revision ID: c2d3attrib01
Revises: b1z2cockpit3
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa

revision = "c2d3attrib01"
down_revision = "b1z2cockpit3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("utm_source", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("utm_medium", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("utm_campaign", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("utm_term", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("utm_content", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("gclid", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("msclkid", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("referrer", sa.String(1024), nullable=True))
    op.add_column("users", sa.Column("landing_page", sa.String(1024), nullable=True))
    op.add_column("users", sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_utm_source", "users", ["utm_source"])
    op.create_index("ix_users_utm_campaign", "users", ["utm_campaign"])


def downgrade() -> None:
    op.drop_index("ix_users_utm_campaign", table_name="users")
    op.drop_index("ix_users_utm_source", table_name="users")
    op.drop_column("users", "attributed_at")
    op.drop_column("users", "landing_page")
    op.drop_column("users", "referrer")
    op.drop_column("users", "msclkid")
    op.drop_column("users", "gclid")
    op.drop_column("users", "utm_content")
    op.drop_column("users", "utm_term")
    op.drop_column("users", "utm_campaign")
    op.drop_column("users", "utm_medium")
    op.drop_column("users", "utm_source")
