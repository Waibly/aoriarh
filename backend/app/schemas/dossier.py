import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DossierCreate(BaseModel):
    model_config = {"extra": "forbid"}
    organisation_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    creation_key: uuid.UUID
    conversation_id: uuid.UUID | None = None
    entry_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    expected_case_version: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Le nom est obligatoire")
        return value


class DossierUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    instructions: str | None = Field(default=None, max_length=10_000)
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Le nom est obligatoire")
        return value


class EntryCreate(BaseModel):
    model_config = {"extra": "forbid"}
    label: str = Field(min_length=1, max_length=500)
    value: str = Field(min_length=1, max_length=20_000)
    expected_case_version: int = Field(ge=1)

    @field_validator("label", "value")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Le libellé et la valeur sont obligatoires")
        return value


class DossierDocumentAction(BaseModel):
    model_config = {"extra": "forbid"}
    operation: Literal["attach", "rename", "remove"]
    description: str | None = Field(default=None, max_length=20000)
    document_id: uuid.UUID | None = None
    link_id: uuid.UUID | None = None
    expected_case_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=500)


class ConversationRename(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field(min_length=1, max_length=500)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Le titre est obligatoire")
        return value
