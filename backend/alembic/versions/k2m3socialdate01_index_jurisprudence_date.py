"""Index exact-date jurisprudence lookups without blocking document writes.

Revision ID: k2m3socialdate01
Revises: k1l2case_refs01
"""

from alembic import op

revision = "k2m3socialdate01"
down_revision = "k1l2case_refs01"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        op.execute("SET statement_timeout = '300s'")
        try:
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_documents_jurisprudence_date "
                "ON documents (source_type, chambre, date_decision)"
            )
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")


def downgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_documents_jurisprudence_date")
