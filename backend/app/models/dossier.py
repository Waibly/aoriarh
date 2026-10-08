"""Named workspaces reuse the conversation case file and chat pipeline."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class Dossier(TimestampMixin, Base):
    __tablename__ = "dossiers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    case_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_files.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    creation_key: Mapped[uuid.UUID] = mapped_column(unique=True)
