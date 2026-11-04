from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StripeWebhookEvent(Base):
    """Stripe event already processed.

    Stripe may deliver the same event more than once. Recording its id in the
    same transaction as its effects makes a redelivery a no-op (no second
    e-mail, no second state change).
    """

    __tablename__ = "stripe_webhook_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
