"""add_fiches_table

Revision ID: ff1a2b3fiches
Revises: dd4e5f6purge8
Create Date: 2026-06-15 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ff1a2b3fiches"
down_revision: Union[str, None] = "dd4e5f6purge8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fiches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fiches_organisation_id"), "fiches", ["organisation_id"])
    op.create_index(op.f("ix_fiches_user_id"), "fiches", ["user_id"])
    op.create_index(op.f("ix_fiches_message_id"), "fiches", ["message_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_fiches_message_id"), table_name="fiches")
    op.drop_index(op.f("ix_fiches_user_id"), table_name="fiches")
    op.drop_index(op.f("ix_fiches_organisation_id"), table_name="fiches")
    op.drop_table("fiches")
