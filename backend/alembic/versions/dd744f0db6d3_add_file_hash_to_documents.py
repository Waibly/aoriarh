"""add_file_hash_to_documents

Revision ID: dd744f0db6d3
Revises: 068057ea672a
Create Date: 2026-02-25 00:47:52.945007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd744f0db6d3'
down_revision: Union[str, None] = '068057ea672a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("file_hash", sa.String(64), nullable=True))
    op.create_index(
        "ix_documents_org_hash",
        "documents",
        ["organisation_id", "file_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_org_hash", table_name="documents")
    op.drop_column("documents", "file_hash")
