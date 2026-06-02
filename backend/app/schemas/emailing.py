import uuid
from datetime import datetime

from pydantic import BaseModel


# --- Templates ---

class EmailTemplateCreate(BaseModel):
    name: str
    subject: str
    preview_text: str | None = None
    html_body: str


class EmailTemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    preview_text: str | None = None
    html_body: str | None = None


class EmailTemplateRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    subject: str
    preview_text: str | None = None
    html_body: str
    created_at: datetime
    updated_at: datetime


# --- Sequences ---

class StepBranchCreate(BaseModel):
    condition: str  # "opened_and_clicked", "opened_not_clicked", "not_opened"
    template_id: uuid.UUID


class StepBranchRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    condition: str
    template_id: uuid.UUID
    template_name: str | None = None
    template_subject: str | None = None


class SequenceStepCreate(BaseModel):
    template_id: uuid.UUID | None = None
    position: int
    delay_days: int = 0
    branches: list[StepBranchCreate] = []


class SequenceStepRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    template_id: uuid.UUID | None = None
    position: int
    delay_days: int
    template_name: str | None = None
    template_subject: str | None = None
    branches: list[StepBranchRead] = []


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
    sent_count: int = 0
    created_at: datetime
    updated_at: datetime


# --- Waves (vagues d'envoi) ---

class WaveScheduleRequest(BaseModel):
    count: int = 100
    scheduled_at: datetime


class CampaignWaveRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    number: int
    scheduled_at: datetime
    recipient_count: int
    sent_count: int = 0
    done_count: int = 0
    status: str = "scheduled"  # scheduled | sending | done


class CampaignWavesOverview(BaseModel):
    campaign_id: uuid.UUID
    status: str
    total_recipients: int
    pending_count: int
    daily_limit: int = 300
    wave_max_size: int = 100
    waves: list[CampaignWaveRead] = []


class WaveContact(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    status: str = "active"  # active | completed | bounced | unsubscribed | failed
    sent: bool = False
    sent_at: datetime | None = None
    opened: bool = False
    clicked: bool = False


# --- Stats ---

class CampaignBranchStats(BaseModel):
    condition: str
    template_name: str | None = None
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    bounced: int = 0
    unsubscribed: int = 0


class CampaignStepStats(BaseModel):
    step_position: int
    template_name: str | None = None
    delay_days: int
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    bounced: int = 0
    unsubscribed: int = 0
    branches: list[CampaignBranchStats] = []


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
