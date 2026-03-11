"""document_org_nullable

Revision ID: 068057ea672a
Revises: 83a41dd9a782
Create Date: 2026-02-25 00:20:27.558374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '068057ea672a'
down_revision: Union[str, None] = '83a41dd9a782'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("documents_organisation_id_fkey", "documents", type_="foreignkey")
    op.alter_column("documents", "organisation_id", nullable=True)
    op.create_foreign_key(
        "documents_organisation_id_fkey",
        "documents",
        "organisations",
        ["organisation_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("documents_organisation_id_fkey", "documents", type_="foreignkey")
    op.alter_column("documents", "organisation_id", nullable=False)
    op.create_foreign_key(
        "documents_organisation_id_fkey",
        "documents",
        "organisations",
        ["organisation_id"],
        ["id"],
    )
