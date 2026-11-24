"""Platform settings changed at runtime from the admin (no redeploy).

Each setting is a validated pydantic model stored as JSON under one key. A missing
or unreadable row falls back to the model defaults, which are always the safe ones.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform_setting import PlatformSetting

logger = logging.getLogger(__name__)

QUALITY_REVIEW_KEY = "quality_review"
_CACHE_TTL_SECONDS = 30.0


class QualityReviewChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arithmetic: bool = True
    citations: bool = True
    llm: bool = True


class QualityReviewSettings(BaseModel):
    """Automated quality review of answers.

    off: nothing runs, nothing is spent. shadow: every check runs and is recorded,
    nobody is alerted (used to measure false alarms before relying on it).
    """

    model_config = ConfigDict(extra="forbid")
    mode: Literal["off", "shadow"] = "off"
    # customers: every answer except to platform staff; paying: active subscriptions only.
    scope: Literal["customers", "paying", "all"] = "customers"
    checks: QualityReviewChecks = Field(default_factory=QualityReviewChecks)
    reviewer_model: Literal["gpt-5.2", "gpt-5.6-terra", "gpt-5", "gpt-5-mini"] = "gpt-5.2"
    monthly_budget_usd: float = Field(default=30.0, ge=0, le=1000)


_cache: dict[str, tuple[float, BaseModel]] = {}


def _parse(value: object) -> QualityReviewSettings:
    try:
        return QualityReviewSettings.model_validate(value or {})
    except ValidationError:
        logger.exception("Invalid stored quality review settings: using safe defaults")
        return QualityReviewSettings()


async def get_quality_review_settings(
    db: AsyncSession, *, use_cache: bool = True
) -> QualityReviewSettings:
    if settings.quality_review_force_off:
        return QualityReviewSettings(mode="off")
    cached = _cache.get(QUALITY_REVIEW_KEY)
    if use_cache and cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]  # type: ignore[return-value]
    row = await db.get(PlatformSetting, QUALITY_REVIEW_KEY)
    value = _parse(row.value if row else None)
    _cache[QUALITY_REVIEW_KEY] = (time.monotonic(), value)
    return value


async def save_quality_review_settings(
    db: AsyncSession, value: QualityReviewSettings, *, user_id: uuid.UUID | None
) -> QualityReviewSettings:
    row = (
        await db.execute(select(PlatformSetting).where(PlatformSetting.key == QUALITY_REVIEW_KEY))
    ).scalar_one_or_none()
    data = value.model_dump()
    if row is None:
        db.add(PlatformSetting(key=QUALITY_REVIEW_KEY, value=data, updated_by=user_id))
    else:
        row.value = data
        row.updated_by = user_id
    await db.commit()
    _cache.pop(QUALITY_REVIEW_KEY, None)
    return value


def clear_cache() -> None:
    _cache.clear()
