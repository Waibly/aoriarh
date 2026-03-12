import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class AccountMember(TimestampMixin, Base):
    __tablename__ = "account_members"
    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_account_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    role_in_org: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    access_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    selected_org_ids: Mapped[str | None] = mapped_column(Text, nullable=True)

    account = relationship("Account", back_populates="members")
    user = relationship("User", back_populates="account_memberships")
