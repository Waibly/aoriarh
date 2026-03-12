import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_email_org", "email", "organisation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organisations.id"), nullable=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    role_in_org: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    token: Mapped[uuid.UUID] = mapped_column(unique=True, default=generate_uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    access_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    selected_org_ids: Mapped[str | None] = mapped_column(Text, nullable=True)

    organisation = relationship("Organisation", backref="invitations")
    account = relationship("Account")
    inviter = relationship("User", foreign_keys=[invited_by])
