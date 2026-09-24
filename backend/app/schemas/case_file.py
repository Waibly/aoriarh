import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CaseEntryActionRequest(BaseModel):
    model_config = {"extra": "forbid", "strict": True}

    operation: Literal["confirm", "correct", "contest", "archive"]
    expected_case_version: int = Field(ge=1)
    value: str | None = Field(default=None, max_length=20_000)
    comment: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def correction_has_a_value(self):
        if self.operation == "correct" and self.value is None:
            raise ValueError("correction_value_required")
        if self.operation != "correct" and self.value is not None:
            raise ValueError("value_only_allowed_for_correction")
        return self


class CaseEntryRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entry_type: str
    key: str | None
    label: str
    value_text: str | None
    value_json: dict | list | None
    status: str
    valid_from: datetime | None
    valid_to: datetime | None
    source_kind: str
    source_message_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    source_extraction_id: uuid.UUID | None
    source_excerpt: str | None
    supersedes_entry_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CaseHistoryImport(BaseModel):
    model_config = {"extra": "forbid"}
    message_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    expected_case_version: int = Field(ge=1)


class CaseTaskRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    task_type: str
    question: str
    status: str
    depends_on: list = Field(default_factory=list)
    relevant_entry_ids: list = Field(default_factory=list)
    required_document_ids: list = Field(default_factory=list)
    created_from_message_id: uuid.UUID | None
    result_message_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CaseDocumentLinkRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    document_id: uuid.UUID | None
    extraction_id: uuid.UUID | None
    role: str | None
    document_name: str
    source_sha256: str | None
    reading_scope: str | None
    added_from_message_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CaseFileRead(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    version: int
    status: str
    inherited_context: dict[str, str | bool | None] | None
    entries: list[CaseEntryRead] = Field(default_factory=list)
    tasks: list[CaseTaskRead] = Field(default_factory=list)
    documents: list[CaseDocumentLinkRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
