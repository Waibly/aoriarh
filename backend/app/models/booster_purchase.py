import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class BoosterPurchase(TimestampMixin, Base):
    """One-shot purchase of +200 questions (the "booster" pack).

    Boosters are consumed after the regular monthly quota is exhausted
    and stay available until fully consumed (expires_at is unused).
    """

    __tablename__ = "booster_purchases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    questions_purchased: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    questions_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )

    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", back_populates="booster_purchases"
    )
