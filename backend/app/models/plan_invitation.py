import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class PlanInvitation(TimestampMixin, Base):
    __tablename__ = "plan_invitations"
    __table_args__ = (Index("ix_plan_invitations_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    token: Mapped[uuid.UUID] = mapped_column(unique=True, default=generate_uuid, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="invite")
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    creator = relationship("User", foreign_keys=[created_by])
    redemptions = relationship("PlanInvitationRedemption", back_populates="plan_invitation")


class PlanInvitationRedemption(TimestampMixin, Base):
    __tablename__ = "plan_invitation_redemptions"
    __table_args__ = (
        Index(
            "ix_plan_inv_redemptions_unique",
            "plan_invitation_id",
            "account_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    plan_invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plan_invitations.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    plan_invitation = relationship("PlanInvitation", back_populates="redemptions")
    account = relationship("Account")
    user = relationship("User")
