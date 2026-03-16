"""Suivi des numéros BOCC traités."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class BoccIssue(Base):
    """Historique des numéros BOCC téléchargés et traités."""

    __tablename__ = "bocc_issues"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    numero: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # ex: "2025-52"
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    avenants_count: Mapped[int] = mapped_column(Integer, default=0)
    avenants_ingested: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="processed")  # processed | error
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
