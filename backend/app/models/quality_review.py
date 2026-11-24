import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class QualityReview(TimestampMixin, Base):
    """One automated quality check of one assistant answer, for one reviewer version."""

    __tablename__ = "quality_reviews"
    __table_args__ = (
        UniqueConstraint("message_id", "reviewer_version", name="uq_quality_review_message"),
        Index("ix_quality_reviews_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    # Deleted with the answer (account purge, conversation deletion): never kept alone.
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # shadow: recorded only. Later modes (alerts, corrections) reuse the same rows.
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    # pending | running | clean | flagged | failed | skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(50))
    checks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reviewer_model: Mapped[str | None] = mapped_column(String(60))
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))

    findings = relationship(
        "QualityFinding",
        back_populates="review",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class QualityFinding(TimestampMixin, Base):
    """An error (not an imprecision) found in an answer, with the passages that prove it."""

    __tablename__ = "quality_findings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # arithmetic | citation | llm
    check: Mapped[str] = mapped_column(String(20), nullable=False)
    # montant | date | article | contradiction | conclusion | citation_introuvable
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    answer_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_label: Mapped[str | None] = mapped_column(String(500))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_fix: Mapped[str | None] = mapped_column(Text)
    # confirmed: certain (program) or upheld by the counter-check; refuted: the
    # counter-check rejected it; unanchored: quotes not found verbatim. Only
    # confirmed findings will ever reach a person.
    validation: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    validation_reason: Mapped[str | None] = mapped_column(Text)
    # open | dismissed | confirmed (human decision, lot 2)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    review = relationship("QualityReview", back_populates="findings", lazy="raise")
