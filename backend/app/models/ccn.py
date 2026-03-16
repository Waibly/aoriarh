import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class CcnReference(Base):
    """Table de référence des conventions collectives (peuplée depuis KALI)."""

    __tablename__ = "ccn_reference"

    idcc: Mapped[str] = mapped_column(String(4), primary_key=True)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    titre_court: Mapped[str | None] = mapped_column(String(255))
    kali_id: Mapped[str | None] = mapped_column(String(30))
    etat: Mapped[str | None] = mapped_column(String(30))
    last_api_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganisationConvention(TimestampMixin, Base):
    """Relation M2M entre une organisation et ses conventions collectives."""

    __tablename__ = "organisation_conventions"
    __table_args__ = (
        UniqueConstraint("organisation_id", "idcc", name="uq_org_convention"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idcc: Mapped[str] = mapped_column(
        ForeignKey("ccn_reference.idcc"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | fetching | indexing | ready | error
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    articles_count: Mapped[int | None] = mapped_column(Integer)
    source_date: Mapped[str | None] = mapped_column(String(10))  # Most recent modifDate from KALI (YYYY-MM-DD)
    use_custom: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # True = user uploaded their own CCN
    error_message: Mapped[str | None] = mapped_column(Text)

    organisation = relationship("Organisation", back_populates="conventions")
    ccn = relationship("CcnReference", lazy="joined")
