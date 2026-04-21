import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class SubscriptionAddon(TimestampMixin, Base):
    """Paid add-on attached to a commercial Subscription.

    addon_type:
      - "extra_user"   → +1 user slot (max 3 per subscription)
      - "extra_org"    → +1 organisation
      - "extra_docs"   → +500 documents for any org of the account
    """

    __tablename__ = "subscription_addons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    addon_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    stripe_subscription_item_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    # Relations
    subscription: Mapped["Subscription"] = relationship(  # noqa: F821
        "Subscription", back_populates="addons"
    )
