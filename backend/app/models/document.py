import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organisations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    norme_niveau: Mapped[int | None] = mapped_column(Integer)
    norme_poids: Mapped[float | None] = mapped_column(Float)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    indexation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer)
    file_format: Mapped[str | None] = mapped_column(String(50))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    indexation_duration_ms: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    indexation_progress: Mapped[int | None] = mapped_column(Integer)
    indexation_error: Mapped[str | None] = mapped_column(String(500))

    # --- Métadonnées jurisprudence (nullable, renseignées uniquement pour les arrêts) ---
    juridiction: Mapped[str | None] = mapped_column(String(100))
    chambre: Mapped[str | None] = mapped_column(String(100))
    formation: Mapped[str | None] = mapped_column(String(100))
    numero_pourvoi: Mapped[str | None] = mapped_column(String(50))
    date_decision: Mapped[date | None] = mapped_column(Date)
    solution: Mapped[str | None] = mapped_column(String(200))
    publication: Mapped[str | None] = mapped_column(String(50))

    organisation = relationship("Organisation", back_populates="documents")
    uploader = relationship("User", foreign_keys=[uploaded_by])
