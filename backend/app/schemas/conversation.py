import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from app.rag.intent_router import is_security_response


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
    # Nécessaire au calcul mais jamais exposée telle quelle au client.
    rag_trace: dict | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def fiche_eligible(self) -> bool:
        """Les réponses de sécurité ne peuvent pas devenir des fiches PDF."""
        return self.role == "assistant" and not is_security_response(
            self.content,
            self.rag_trace,
        )


class ConversationReadWithMessages(ConversationRead):
    messages: list[MessageRead] = []


class MessageFeedback(BaseModel):
    feedback: str | None = Field(None, pattern=r"^(up|down)$")
    comment: str | None = Field(None, max_length=1000)


class LinkedInPostResponse(BaseModel):
    """Post brut et contrôles informatifs, sans post-traitement du contenu."""

    content: str
    character_count: int
    references: list[str]
    warnings: list[str]


class SocialMediaImageResponse(BaseModel):
    """Image PNG rendue depuis le HTML exact."""

    filename: str
    content_base64: str


class SocialMediaGenerationResponse(BaseModel):
    """Sortie LLM brute, HTML éditable et rendu optionnel associé."""

    raw_content: str
    html: str
    images: list[SocialMediaImageResponse]
    references: list[str]
    warnings: list[str]
    render_error: str | None = None


class SocialMediaRenderRequest(BaseModel):
    """HTML explicitement édité par l'administrateur, jamais réécrit."""

    html: str = Field(..., min_length=1, max_length=2_000_000)


class SocialMediaRenderResponse(BaseModel):
    images: list[SocialMediaImageResponse]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
