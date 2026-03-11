import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    organisation_id: uuid.UUID
    title: str | None = None


class ConversationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    organisation_id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    sources: list[dict] | None
    feedback: str | None
    feedback_comment: str | None
    created_at: datetime


class ConversationReadWithMessages(ConversationRead):
    messages: list[MessageRead] = []


class MessageFeedback(BaseModel):
    feedback: str | None = Field(None, pattern=r"^(up|down)$")
    comment: str | None = Field(None, max_length=1000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)


class ChatResponse(BaseModel):
    message: MessageRead
    answer: MessageRead
