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

    # Plan (both technical plans gratuit/invite/vip and commercial solo/equipe/groupe)
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default="gratuit", server_default="gratuit"
    )
    plan_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    plan_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Lifecycle status independent from the plan value.
    # active | trialing | past_due | suspended | canceled
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )

    # Stripe customer (only set for commercial plans). One customer per account,
    # can carry several subscriptions over time (history).
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    # Relations
    owner: Mapped["User"] = relationship("User", back_populates="owned_account")  # noqa: F821
    organisations: Mapped[list["Organisation"]] = relationship(  # noqa: F821
        "Organisation", back_populates="account"
    )
    members: Mapped[list["AccountMember"]] = relationship(  # noqa: F821
        "AccountMember", back_populates="account", lazy="selectin"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(  # noqa: F821
        "Subscription", back_populates="account", cascade="all, delete-orphan"
    )
    booster_purchases: Mapped[list["BoosterPurchase"]] = relationship(  # noqa: F821
        "BoosterPurchase", back_populates="account", cascade="all, delete-orphan"
    )
    monthly_usage: Mapped[list["MonthlyQuestionUsage"]] = relationship(  # noqa: F821
        "MonthlyQuestionUsage", back_populates="account", cascade="all, delete-orphan"
    )
