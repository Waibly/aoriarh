"""Add not_subject_to_ccn flag to organisations

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-05-22

Permet à un manager de déclarer qu'une organisation n'est pas
soumise à une convention collective. Le pipeline RAG s'appuie
sur ce flag pour exclure les chunks CCN du retrieval et adapter
le prompt système.
"""

import sqlalchemy as sa
from alembic import op

revision = "v7w8x9y0z1a2"
down_revision = "u6v7w8x9y0z1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column(
            "not_subject_to_ccn",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("organisations", "not_subject_to_ccn")
