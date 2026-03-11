import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_email_org", "email", "organisation_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id"), nullable=False
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    role_in_org: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    token: Mapped[uuid.UUID] = mapped_column(unique=True, default=generate_uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    organisation = relationship("Organisation", backref="invitations")
    inviter = relationship("User", foreign_keys=[invited_by])
