"""Add the versioned conversation case-file foundation.

Revision ID: h7i8casefile01
Revises: g6h7chatdocs01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "h7i8casefile01"
down_revision = "g6h7chatdocs01"
branch_labels = None
depends_on = None


def upgrade():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "case_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(30), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id"),
    )
    op.create_index("ix_case_files_conversation_id", "case_files", ["conversation_id"])

    op.create_table(
        "case_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_file_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("key", sa.String(150), nullable=True),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_json", json_type, nullable=True),
        sa.Column("status", sa.String(30), server_default="active", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("source_extraction_id", sa.Uuid(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("supersedes_entry_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["case_file_id"], ["case_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_extraction_id"], ["document_extractions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["supersedes_entry_id"], ["case_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "case_file_id",
        "status",
        "source_message_id",
        "source_document_id",
        "source_extraction_id",
        "supersedes_entry_id",
        "created_by_user_id",
    ):
        op.create_index(f"ix_case_entries_{column}", "case_entries", [column])

    op.create_table(
        "case_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_file_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("depends_on", json_type, server_default="[]", nullable=False),
        sa.Column("relevant_entry_ids", json_type, server_default="[]", nullable=False),
        sa.Column("required_document_ids", json_type, server_default="[]", nullable=False),
        sa.Column("created_from_message_id", sa.Uuid(), nullable=True),
        sa.Column("result_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["case_file_id"], ["case_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_from_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["result_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("case_file_id", "status", "created_from_message_id", "result_message_id"):
        op.create_index(f"ix_case_tasks_{column}", "case_tasks", [column])

    op.create_table(
        "case_document_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_file_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("extraction_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column("document_name", sa.String(500), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("reading_scope", sa.Text(), nullable=True),
        sa.Column("added_from_message_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["case_file_id"], ["case_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["document_extractions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["added_from_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_file_id", "document_id", "extraction_id", name="uq_case_document_version"
        ),
    )
    for column in ("case_file_id", "document_id", "extraction_id", "added_from_message_id"):
        op.create_index(f"ix_case_document_links_{column}", "case_document_links", [column])

    op.create_table(
        "case_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_file_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(30), nullable=False),
        sa.Column("organisation_context_snapshot", json_type, nullable=True),
        sa.Column("raw_planner_output", sa.Text(), nullable=True),
        sa.Column("structured_delta", json_type, nullable=True),
        sa.Column("technical_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["case_file_id"], ["case_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("case_file_id", "event_type", "source_message_id"):
        op.create_index(f"ix_case_events_{column}", "case_events", [column])


def downgrade():
    op.drop_table("case_events")
    op.drop_table("case_document_links")
    op.drop_table("case_tasks")
    op.drop_table("case_entries")
    op.drop_table("case_files")
