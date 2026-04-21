import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Subscription(TimestampMixin, Base):
    """A commercial Stripe subscription attached to an Account.

    Technical plans (gratuit/invite/vip) do not create rows here — they are
    tracked directly on the Account (plan, plan_expires_at).
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Plan snapshot — stays in sync with Account.plan while active.
    plan: Mapped[str] = mapped_column(String(20), nullable=False)  # solo | equipe | groupe
    billing_cycle: Mapped[str] = mapped_column(String(10), nullable=False)  # monthly | yearly
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active | trialing | past_due | canceled | unpaid

    # Stripe identifiers
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    # Billing period (driven by Stripe webhooks)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Cancellation
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relations
    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", back_populates="subscriptions"
    )
    addons: Mapped[list["SubscriptionAddon"]] = relationship(  # noqa: F821
        "SubscriptionAddon", back_populates="subscription", cascade="all, delete-orphan"
    )
