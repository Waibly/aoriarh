"""Local document descriptions for dossier links."""

from alembic import op
import sqlalchemy as sa

revision = "k0l1dossiers02"
down_revision = "j9k0dossiers01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "case_document_links",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("case_document_links", "description")
