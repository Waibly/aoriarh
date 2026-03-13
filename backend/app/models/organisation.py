import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Organisation(TimestampMixin, Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    forme_juridique: Mapped[str | None] = mapped_column(String(100))
    taille: Mapped[str | None] = mapped_column(String(50))
    convention_collective: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secteur_activite: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )

    account: Mapped["Account | None"] = relationship("Account", back_populates="organisations")  # noqa: F821
    memberships = relationship("Membership", back_populates="organisation", lazy="selectin")
    documents = relationship("Document", back_populates="organisation", lazy="selectin")
    conversations = relationship("Conversation", back_populates="organisation", lazy="selectin")
    conventions = relationship("OrganisationConvention", back_populates="organisation", lazy="selectin")
