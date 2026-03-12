import uuid
from datetime import datetime

from pydantic import BaseModel


class AccountRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    plan: str
    plan_expires_at: datetime | None
    plan_assigned_at: datetime | None
    created_at: datetime
