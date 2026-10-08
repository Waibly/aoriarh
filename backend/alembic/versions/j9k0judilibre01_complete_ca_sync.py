"""Durable Judilibre identifiers, checkpoints and indexing outbox.

Revision ID: j9k0judilibre01
Revises: l1m2feedback03
"""

import sqlalchemy as sa
from alembic import op

revision = "j9k0judilibre01"
down_revision = "l1m2feedback03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_documents_judilibre_legacy",
        "documents",
        ["juridiction", "numero_pourvoi", "date_decision", "file_hash"],
        postgresql_where=sa.text("organisation_id IS NULL AND source_type = 'arret_cour_appel'"),
    )
    op.create_table(
        "judilibre_records",
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("needs_indexing", sa.Boolean(), nullable=False),
        sa.Column("enqueue_attempts", sa.Integer(), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "judilibre_scans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(200), nullable=False, unique=True),
        sa.Column("date_start", sa.Date(), nullable=False),
        sa.Column("date_end", sa.Date(), nullable=False),
        sa.Column("date_type", sa.String(20), nullable=False),
        sa.Column("cursor", sa.Text()),
        sa.Column("expected_total", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("sync_log_id", sa.Uuid(), sa.ForeignKey("sync_logs.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "judilibre_scan_items",
        sa.Column(
            "scan_id",
            sa.Uuid(),
            sa.ForeignKey("judilibre_scans.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source_id", sa.String(64), primary_key=True),
    )


def downgrade():
    op.drop_table("judilibre_scan_items")
    op.drop_table("judilibre_scans")
    op.drop_table("judilibre_records")
    op.drop_index("ix_documents_judilibre_legacy", table_name="documents")
