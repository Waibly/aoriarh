"""Durable identities, scan checkpoints and indexing outbox for Judilibre."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class JudilibreRecord(TimestampMixin, Base):
    __tablename__ = "judilibre_records"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    needs_indexing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enqueue_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JudilibreScan(TimestampMixin, Base):
    __tablename__ = "judilibre_scans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    date_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_end: Mapped[date] = mapped_column(Date, nullable=False)
    date_type: Mapped[str] = mapped_column(String(20), nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text)
    expected_total: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    sync_log_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sync_logs.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class JudilibreScanItem(Base):
    __tablename__ = "judilibre_scan_items"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("judilibre_scans.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
