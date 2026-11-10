"""Réponses au questionnaire de fin d'essai.

Une réponse par compte (la dernière remplace la précédente). Le lien vers le
compte est retiré lors de la purge RGPD : la raison, le commentaire et le
nombre de questions posées restent consultables sans identité, pour les
statistiques de conversion.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class TrialFeedback(TimestampMixin, Base):
    __tablename__ = "trial_feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    # NULL once the account has been purged (anonymised response).
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, unique=True, index=True
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Snapshot taken when answering, kept after anonymisation.
    questions_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trial_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
