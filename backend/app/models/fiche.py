import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class Fiche(TimestampMixin, Base):
    """Fiche pratique générée par un utilisateur à partir d'une réponse.

    On stocke le contenu structuré (pas le PDF figé) : le PDF est régénéré à la
    demande avec la date du jour, ce qui évite d'héberger un document juridique
    figé qui périme. Cloisonnement par organisation_id, propriété par user_id.
    """

    __tablename__ = "fiches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    # Message source. Nullable + SET NULL : la fiche survit si le message
    # disparaît un jour.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Contenu structuré (FicheContent sérialisé) + snapshot des sources.
    content: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    sources: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
