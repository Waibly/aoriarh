"""Separate official publication, effective and update dates.

Revision ID: i8j9chronology01
Revises: h7i8casefile01
"""

import sqlalchemy as sa
from alembic import op

revision = "i8j9chronology01"
down_revision = "h7i8casefile01"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("publication_date", "effective_date", "source_updated_date"):
        op.add_column("documents", sa.Column(name, sa.Date(), nullable=True))
        op.create_index(f"ix_documents_{name}", "documents", [name])
    op.add_column("documents", sa.Column("source_url", sa.String(2000), nullable=True))
    # BOSS's historical date is explicitly parsed from the official update label.
    op.execute("UPDATE documents SET source_updated_date = date_decision "
               "WHERE source_type = 'boss' AND organisation_id IS NULL")
    # JORF's historical date_decision may be dateTexte, not publication. No guessing:
    # hydrate publication_date from the official API with the maintenance command.


def downgrade():
    op.drop_column("documents", "source_url")
    for name in ("source_updated_date", "effective_date", "publication_date"):
        op.drop_index(f"ix_documents_{name}", table_name="documents")
        op.drop_column("documents", name)
