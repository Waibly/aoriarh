"""Durable storage intents survive document deletion and process crashes."""

import uuid

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class StorageOperation(TimestampMixin, Base):
    __tablename__ = "storage_operations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    # Deliberately no cascading FK: recovery must survive owner deletion.
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    target_path: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
