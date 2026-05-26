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
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_templates.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sequence = relationship("EmailSequence", back_populates="steps")
    template = relationship("EmailTemplate", back_populates="sequence_steps")


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


class EmailCampaignRecipient(TimestampMixin, Base):
    __tablename__ = "email_campaign_recipients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    brevo_contact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    campaign = relationship("EmailCampaign", back_populates="recipients")
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
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    recipient = relationship("EmailCampaignRecipient", back_populates="events")
