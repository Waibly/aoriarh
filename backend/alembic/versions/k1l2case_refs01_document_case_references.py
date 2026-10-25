"""Keep all joined social case references without rewriting existing documents.

Revision ID: k1l2case_refs01
Revises: j9k0judilibre01
"""

import sqlalchemy as sa

from alembic import op

revision = "k1l2case_refs01"
down_revision = "j9k0judilibre01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "document_case_references",
        sa.Column(
            "document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("number", sa.String(100), primary_key=True),
        sa.Column("decision_date", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_document_case_references_lookup", "document_case_references",
        ["decision_date", "number"],
    )


def downgrade():
    op.drop_index("ix_document_case_references_lookup", table_name="document_case_references")
    op.drop_table("document_case_references")
