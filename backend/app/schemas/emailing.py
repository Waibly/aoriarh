import uuid
from datetime import datetime

from pydantic import BaseModel


# --- Templates ---

class EmailTemplateCreate(BaseModel):
    name: str
    subject: str
    html_body: str


class EmailTemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    html_body: str | None = None


class EmailTemplateRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    subject: str
    html_body: str
    created_at: datetime
    updated_at: datetime


# --- Sequences ---

class SequenceStepCreate(BaseModel):
    template_id: uuid.UUID
    position: int
    delay_days: int = 0


class SequenceStepRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    template_id: uuid.UUID
    position: int
    delay_days: int
    template_name: str | None = None
    template_subject: str | None = None


class EmailSequenceCreate(BaseModel):
    name: str
    steps: list[SequenceStepCreate] = []


class EmailSequenceUpdate(BaseModel):
    name: str | None = None
    steps: list[SequenceStepCreate] | None = None


class EmailSequenceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    status: str
    steps: list[SequenceStepRead] = []
    created_at: datetime
    updated_at: datetime


# --- Campaigns ---

class EmailCampaignCreate(BaseModel):
    name: str
    sequence_id: uuid.UUID
    brevo_list_ids: list[int]
    scheduled_at: datetime | None = None


class EmailCampaignRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    sequence_id: uuid.UUID
    sequence_name: str | None = None
    brevo_list_ids: list[int]
    status: str
    scheduled_at: datetime | None = None
    current_step: int
    recipient_count: int = 0
    created_at: datetime
    updated_at: datetime


# --- Stats ---

class CampaignStepStats(BaseModel):
    step_position: int
    template_name: str | None = None
    delay_days: int
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    bounced: int = 0
    unsubscribed: int = 0


class CampaignStats(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    status: str
    total_recipients: int
    steps: list[CampaignStepStats] = []


# --- Brevo lists (read-only) ---

class BrevoList(BaseModel):
    id: int
    name: str
    total_subscribers: int
    total_blacklisted: int = 0


class BrevoContact(BaseModel):
    id: int
    email: str
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
