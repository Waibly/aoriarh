"""Structured, versioned case data attached to a conversation."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid

JsonValue = JSON().with_variant(JSONB, "postgresql")


class CaseFile(TimestampMixin, Base):
    __tablename__ = "case_files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )

    conversation = relationship("Conversation", back_populates="case_file")
    entries = relationship(
        "CaseEntry",
        back_populates="case_file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseEntry.created_at",
        lazy="raise",
    )
    tasks = relationship(
        "CaseTask",
        back_populates="case_file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseTask.created_at",
        lazy="raise",
    )
    document_links = relationship(
        "CaseDocumentLink",
        back_populates="case_file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseDocumentLink.created_at",
        lazy="raise",
    )
    events = relationship(
        "CaseEvent",
        back_populates="case_file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseEvent.created_at",
        lazy="raise",
    )


class CaseEntry(TimestampMixin, Base):
    __tablename__ = "case_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_json: Mapped[dict | list | None] = mapped_column(JsonValue, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active", index=True
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("case_entries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    case_file = relationship("CaseFile", back_populates="entries")


class CaseTask(TimestampMixin, Base):
    __tablename__ = "case_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending", index=True
    )
    depends_on: Mapped[list] = mapped_column(JsonValue, nullable=False, default=list)
    relevant_entry_ids: Mapped[list] = mapped_column(JsonValue, nullable=False, default=list)
    required_document_ids: Mapped[list] = mapped_column(JsonValue, nullable=False, default=list)
    created_from_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    result_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )

    case_file = relationship("CaseFile", back_populates="tasks")


class CaseDocumentLink(TimestampMixin, Base):
    __tablename__ = "case_document_links"
    __table_args__ = (
        UniqueConstraint(
            "case_file_id", "document_id", "extraction_id", name="uq_case_document_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reading_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_from_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )

    case_file = relationship("CaseFile", back_populates="document_links")


class CaseEvent(TimestampMixin, Base):
    __tablename__ = "case_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    case_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("case_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    organisation_context_snapshot: Mapped[dict | None] = mapped_column(JsonValue, nullable=True)
    raw_planner_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured_delta: Mapped[dict | list | None] = mapped_column(JsonValue, nullable=True)
    technical_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    case_file = relationship("CaseFile", back_populates="events")
