"""Add version-bound extraction records; no backfill or corpus migration.

Revision ID: e4f5docread01
Revises: d3e4security02
"""
import sqlalchemy as sa
from alembic import op

revision = "e4f5docread01"
down_revision = "d3e4security02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_storage_path", sa.String(1000), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(500), nullable=False),
        sa.Column("file_format", sa.String(50), nullable=False),
        sa.Column("extractor_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("text_storage_path", sa.String(1000), nullable=True),
        sa.Column("text_sha256", sa.String(64), nullable=True),
        sa.Column("text_bytes", sa.Integer(), nullable=True),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_extractions_document_id", "document_extractions", ["document_id"])


def downgrade() -> None:
    # Does not delete objects from S3. Export/retention must be resolved before downgrade.
    op.drop_index("ix_document_extractions_document_id", table_name="document_extractions")
    op.drop_table("document_extractions")
