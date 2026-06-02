import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class EmailTemplate(TimestampMixin, Base):
    __tablename__ = "email_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    preview_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)

    sequence_steps = relationship("EmailSequenceStep", back_populates="template")


class EmailSequence(TimestampMixin, Base):
    __tablename__ = "email_sequences"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    steps = relationship(
        "EmailSequenceStep",
        back_populates="sequence",
        order_by="EmailSequenceStep.position",
        cascade="all, delete-orphan",
    )
    campaigns = relationship("EmailCampaign", back_populates="sequence")


class EmailSequenceStep(TimestampMixin, Base):
    __tablename__ = "email_sequence_steps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_sequences.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_templates.id"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sequence = relationship("EmailSequence", back_populates="steps")
    template = relationship("EmailTemplate", back_populates="sequence_steps")
    branches = relationship(
        "EmailSequenceStepBranch",
        back_populates="step",
        cascade="all, delete-orphan",
    )


class EmailSequenceStepBranch(TimestampMixin, Base):
    __tablename__ = "email_sequence_step_branches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    step_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_sequence_steps.id", ondelete="CASCADE"), nullable=False
    )
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_templates.id"), nullable=False
    )

    step = relationship("EmailSequenceStep", back_populates="branches")
    template = relationship("EmailTemplate")


class EmailCampaign(TimestampMixin, Base):
    __tablename__ = "email_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_sequences.id"), nullable=False
    )
    brevo_list_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sequence = relationship("EmailSequence", back_populates="campaigns")
    recipients = relationship(
        "EmailCampaignRecipient",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    waves = relationship(
        "EmailCampaignWave",
        back_populates="campaign",
        order_by="EmailCampaignWave.number",
        cascade="all, delete-orphan",
    )


class EmailCampaignWave(TimestampMixin, Base):
    """Un envoi planifié d'un sous-ensemble de contacts d'une campagne.

    Les contacts d'une campagne sont chargés « en stock » (wave_id NULL) au
    lancement, puis l'admin programme des vagues de N contacts (max 100) à la
    date de son choix. Chaque contact est verrouillé sur une seule vague, donc
    ne peut jamais recevoir deux fois le même envoi.
    """

    __tablename__ = "email_campaign_waves"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    campaign = relationship("EmailCampaign", back_populates="waves")
    recipients = relationship("EmailCampaignRecipient", back_populates="wave")


class EmailCampaignRecipient(TimestampMixin, Base):
    __tablename__ = "email_campaign_recipients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    wave_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_campaign_waves.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    brevo_contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # active | completed | bounced | unsubscribed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Nombre d'échecs d'envoi consécutifs (réinitialisé à 0 après un envoi
    # réussi). Au-delà de MAX_SEND_ATTEMPTS, le contact passe en "failed" et
    # n'est plus retenté.
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Date d'envoi du 1er mail (= date de la vague). Les relances de la
    # séquence (J+3, J+7...) se calculent à partir de cette date, propre à
    # chaque vague. NULL = encore en stock, pas encore programmé.
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    campaign = relationship("EmailCampaign", back_populates="recipients")
    wave = relationship("EmailCampaignWave", back_populates="recipients")
    events = relationship(
        "EmailCampaignEvent",
        back_populates="recipient",
        cascade="all, delete-orphan",
    )


class EmailCampaignEvent(Base):
    __tablename__ = "email_campaign_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_campaign_recipients.id", ondelete="CASCADE"), nullable=False
    )
    step_position: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    branch_condition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    recipient = relationship("EmailCampaignRecipient", back_populates="events")
