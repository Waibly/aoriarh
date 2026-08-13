import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="credentials", server_default="credentials")
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    profil_metier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Internal back-office staff segmentation: "business" | "tech" | None.
    # None = sees everything and lands on the business cockpit. Only meaningful
    # for users with role="admin".
    staff_role: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Attribution marketing du premier contact (capturée sur le site vitrine,
    # transmise à l'inscription). Première visite conservée : jamais écrasée.
    utm_source: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    utm_medium: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    utm_term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    msclkid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    landing_page: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attributed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships = relationship("Membership", back_populates="user", lazy="selectin")
    conversations = relationship("Conversation", back_populates="user", lazy="selectin")
    owned_account = relationship("Account", back_populates="owner", uselist=False, lazy="selectin")
    account_memberships = relationship("AccountMember", back_populates="user", lazy="selectin")
