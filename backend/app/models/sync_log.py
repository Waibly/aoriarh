"""Log des synchronisations automatiques (jurisprudence, CCN)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class SyncLog(Base):
    """Historique des tâches de synchronisation automatique."""

    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    sync_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )  # "jurisprudence" | "ccn"
    idcc: Mapped[str | None] = mapped_column(String(4))  # For CCN syncs
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # "success" | "error" | "skipped" | "no_change"
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
