import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Organisation(TimestampMixin, Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    forme_juridique: Mapped[str | None] = mapped_column(String(100))
    taille: Mapped[str | None] = mapped_column(String(50))

    memberships = relationship("Membership", back_populates="organisation", lazy="selectin")
    documents = relationship("Document", back_populates="organisation", lazy="selectin")
    conversations = relationship("Conversation", back_populates="organisation", lazy="selectin")
