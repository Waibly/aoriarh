"""add_performance_indexes

Revision ID: b7f8e9a0c1d2
Revises: 303953a07506
Create Date: 2026-02-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f8e9a0c1d2"
down_revision: Union[str, None] = "303953a07506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_document_org_status",
        "documents",
        ["organisation_id", "indexation_status"],
    )
    op.create_index(
        "ix_message_conv_created",
        "messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_membership_user_org",
        "memberships",
        ["user_id", "organisation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_membership_user_org", table_name="memberships")
    op.drop_index("ix_message_conv_created", table_name="messages")
    op.drop_index("ix_document_org_status", table_name="documents")
