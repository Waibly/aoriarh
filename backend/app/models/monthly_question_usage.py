import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class MonthlyQuestionUsage(TimestampMixin, Base):
    """Aggregated question count per account per billing period.

    One row per (account, period_start). Incremented atomically on each
    question served. Kept separate from ApiUsageLog for fast quota checks.
    """

    __tablename__ = "monthly_question_usage"
    __table_args__ = (
        UniqueConstraint("account_id", "period_start", name="uq_usage_account_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    questions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quota_for_period: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relations
    account: Mapped["Account"] = relationship(  # noqa: F821
        "Account", back_populates="monthly_usage"
    )
