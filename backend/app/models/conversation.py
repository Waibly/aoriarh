import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    # Soft-delete marker. When set, the conversation is hidden from the
    # chat sidebar but the row + its messages stay in DB so analytics
    # (cost tracking, quality metrics, admin audit) keep working.
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    organisation = relationship("Organisation", back_populates="conversations")
    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message", back_populates="conversation", order_by="Message.created_at", lazy="selectin"
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[dict | None] = mapped_column(JSON)
    feedback: Mapped[str | None] = mapped_column(String(20))
    feedback_comment: Mapped[str | None] = mapped_column(Text)
    # Admin Quality v1: full RAG pipeline trace + per-question latency.
    # Populated only on assistant messages, only after the feature was deployed.
    # JSON in Postgres compiles to JSONB via the variant; SQLite (tests) gets TEXT.
    rag_trace: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Stable link to api_usage_logs.context_id for live cost lookup. The cost
    # of a message is computed via SUM(api_usage_logs.cost_usd WHERE
    # context_id = question_id), never persisted, so /admin/quality and
    # /admin/costs always agree.
    question_id: Mapped[uuid.UUID | None] = mapped_column(index=True, nullable=True)

    conversation = relationship("Conversation", back_populates="messages")
