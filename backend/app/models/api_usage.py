import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class ApiPricing(Base):
    """Configurable pricing table for API providers/models."""

    __tablename__ = "api_pricing"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    price_input_per_million: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=False, comment="USD per 1M input tokens"
    )
    price_output_per_million: Mapped[float] = mapped_column(
        Numeric(10, 4), nullable=True, comment="USD per 1M output tokens (null for embeddings)"
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_api_pricing_provider_model", "provider", "model"),
    )


class ApiUsageLog(Base):
    """Log of every paid API call (OpenAI, Voyage AI)."""

    __tablename__ = "api_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # API call info
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    operation_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="condense | expand | generate | embedding | rerank",
    )

    # Token counts
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Computed cost at time of logging
    cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, default=0
    )

    # Attribution
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Context
    context_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="question | ingestion"
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_api_usage_logs_created_at", "created_at"),
        Index("ix_api_usage_logs_organisation_id", "organisation_id"),
        Index("ix_api_usage_logs_user_id", "user_id"),
        Index("ix_api_usage_logs_context", "context_type", "context_id"),
    )
