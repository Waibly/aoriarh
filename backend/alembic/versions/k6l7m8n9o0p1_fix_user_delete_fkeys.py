"""Fix foreign keys for user deletion + add cost snapshot columns

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-03-14

"""

import sqlalchemy as sa
from alembic import op

revision = "k6l7m8n9o0p1"
down_revision = "j5k6l7m8n9o0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # documents.uploaded_by: make nullable + SET NULL on delete
    op.alter_column("documents", "uploaded_by", nullable=True)
    op.drop_constraint("documents_uploaded_by_fkey", "documents", type_="foreignkey")
    op.create_foreign_key(
        "documents_uploaded_by_fkey",
        "documents",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # audit_logs.user_id: CASCADE on delete
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add snapshot columns to api_usage_logs for preserving names after deletion
    op.add_column(
        "api_usage_logs",
        sa.Column("user_email_snapshot", sa.String(255), nullable=True),
    )
    op.add_column(
        "api_usage_logs",
        sa.Column("organisation_name_snapshot", sa.String(255), nullable=True),
    )

    # Backfill existing rows with current user emails and org names
    op.execute("""
        UPDATE api_usage_logs
        SET user_email_snapshot = u.email
        FROM users u
        WHERE api_usage_logs.user_id = u.id
          AND api_usage_logs.user_email_snapshot IS NULL
    """)
    op.execute("""
        UPDATE api_usage_logs
        SET organisation_name_snapshot = o.name
        FROM organisations o
        WHERE api_usage_logs.organisation_id = o.id
          AND api_usage_logs.organisation_name_snapshot IS NULL
    """)


def downgrade() -> None:
    # Drop snapshot columns
    op.drop_column("api_usage_logs", "organisation_name_snapshot")
    op.drop_column("api_usage_logs", "user_email_snapshot")

    # Revert audit_logs FK
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
    )

    # Revert documents FK
    op.drop_constraint("documents_uploaded_by_fkey", "documents", type_="foreignkey")
    op.create_foreign_key(
        "documents_uploaded_by_fkey",
        "documents",
        "users",
        ["uploaded_by"],
        ["id"],
    )
    op.alter_column("documents", "uploaded_by", nullable=False)
