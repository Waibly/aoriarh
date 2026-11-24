"""Contrôle qualité automatisé des réponses : réglages plateforme, contrôles, constats

Revision ID: t9quality01
Revises: s8horsleg01
Create Date: 2026-11-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "t9quality01"
down_revision: str | None = "s8horsleg01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "quality_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_version", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("skip_reason", sa.String(length=50), nullable=True),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("reviewer_model", sa.String(length=60), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "reviewer_version", name="uq_quality_review_message"),
    )
    op.create_index("ix_quality_reviews_message_id", "quality_reviews", ["message_id"])
    op.create_index("ix_quality_reviews_status", "quality_reviews", ["status"])
    op.create_index("ix_quality_reviews_created_at", "quality_reviews", ["created_at"])

    op.create_table(
        "quality_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "review_id",
            sa.Uuid(),
            sa.ForeignKey("quality_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("answer_excerpt", sa.Text(), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("source_label", sa.String(length=500), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("proposed_fix", sa.Text(), nullable=True),
        sa.Column("validation", sa.String(length=20), nullable=False),
        sa.Column("validation_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column(
            "decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_findings_review_id", "quality_findings", ["review_id"])
    op.create_index("ix_quality_findings_message_id", "quality_findings", ["message_id"])
    op.create_index("ix_quality_findings_validation", "quality_findings", ["validation"])
    op.create_index("ix_quality_findings_status", "quality_findings", ["status"])


def downgrade() -> None:
    op.drop_table("quality_findings")
    op.drop_table("quality_reviews")
    op.drop_table("platform_settings")
