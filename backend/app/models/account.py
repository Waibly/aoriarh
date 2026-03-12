import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True
    )

    # Plan
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default="gratuit", server_default="gratuit"
    )
    plan_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    plan_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relations
    owner: Mapped["User"] = relationship("User", back_populates="owned_account")  # noqa: F821
    organisations: Mapped[list["Organisation"]] = relationship(  # noqa: F821
        "Organisation", back_populates="account"
    )
    members: Mapped[list["AccountMember"]] = relationship(  # noqa: F821
        "AccountMember", back_populates="account", lazy="selectin"
    )
