"""Run one automated quality review of one assistant answer.

Called from the worker, never from the chat request: a failure or a slow model here
can never delay or break an answer. Idempotent per (answer, reviewer version).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.quality_review import QualityFinding, QualityReview
from app.models.subscription import Subscription
from app.models.user import User
from app.services.platform_settings import QualityReviewSettings, get_quality_review_settings
from app.services.quality_review.deterministic import arithmetic_findings, citation_findings
from app.services.quality_review.llm_reviewer import LlmReviewer, ReviewInput, ReviewSource

logger = logging.getLogger(__name__)

# Bump when a check or a prompt changes: answers can then be reviewed again.
REVIEWER_VERSION = "v1"
_PAYING_STATUSES = {"active", "past_due"}
_HISTORY_MESSAGES = 4
_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _french_date(value: datetime) -> str:
    local = value.astimezone(ZoneInfo("Europe/Paris"))
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}"


def source_texts(sources: object) -> list[ReviewSource]:
    """The passages the answer was written from, as stored with the answer."""
    result: list[ReviewSource] = []
    if not isinstance(sources, list):
        return result
    for item in sources:
        if not isinstance(item, dict):
            continue
        texts = [item.get("full_text") or ""]
        for passage in item.get("context_passages") or []:
            text = passage.get("text") if isinstance(passage, dict) else None
            if text and text not in texts[0]:
                texts.append(text)
        text = "\n\n".join(t for t in texts if t).strip()
        if not text:
            continue
        label = item.get("document_name") or item.get("source_type_label") or "Source"
        articles = item.get("article_nums")
        if isinstance(articles, list) and articles:
            label += " — art. " + ", ".join(str(a) for a in articles[:8])
        result.append(ReviewSource(label=str(label)[:500], text=text))
    return result


async def _in_scope(db: AsyncSession, scope: str, conversation: Conversation) -> bool:
    if scope == "all":
        return True
    user = await db.get(User, conversation.user_id)
    if user is None or user.role == "admin":
        return False
    if scope == "customers":
        return True
    organisation = await db.get(Organisation, conversation.organisation_id)
    if organisation is None or organisation.account_id is None:
        return False
    statuses = (
        await db.execute(
            select(Subscription.status).where(Subscription.account_id == organisation.account_id)
        )
    ).scalars()
    return any(status in _PAYING_STATUSES for status in statuses)


async def month_spend(db: AsyncSession, now: datetime | None = None) -> Decimal:
    now = now or datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (
        await db.execute(
            select(func.coalesce(func.sum(QualityReview.cost_usd), 0)).where(
                QualityReview.created_at >= start
            )
        )
    ).scalar_one()
    return Decimal(total)


async def _review_input(db: AsyncSession, message: Message) -> ReviewInput:
    earlier = (
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == message.conversation_id,
                    Message.created_at < message.created_at,
                )
                .order_by(Message.created_at.desc())
                .limit(_HISTORY_MESSAGES + 1)
            )
        )
        .scalars()
        .all()
    )
    earlier = list(reversed(earlier))
    question = ""
    if earlier and earlier[-1].role == "user":
        question = earlier.pop().content
    return ReviewInput(
        answer=message.content,
        question=question,
        answer_date=_french_date(message.created_at),
        history=[(m.role, m.content) for m in earlier],
        sources=source_texts(message.sources),
    )


def _default_reviewer(model: str) -> LlmReviewer:
    from app.rag.agent import _llm

    return LlmReviewer(_llm, model)


def _default_article_lookup():
    from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
    from app.services.quality_review.deterministic import qdrant_article_lookup

    return qdrant_article_lookup(get_qdrant_client(), COLLECTION_NAME)


async def run_quality_review(
    db: AsyncSession,
    message_id: uuid.UUID,
    *,
    force: bool = False,
    config: QualityReviewSettings | None = None,
    reviewer: LlmReviewer | None = None,
    article_lookup=None,
) -> QualityReview | None:
    """Review one answer. force=True ignores mode and scope (backfill, tests), not budget."""
    config = config or await get_quality_review_settings(db, use_cache=False)
    if config.mode == "off" and not force:
        return None
    message = await db.get(Message, message_id)
    if message is None or message.role != "assistant":
        return None
    conversation = await db.get(Conversation, message.conversation_id)
    if conversation is None:
        return None
    if not force and not await _in_scope(db, config.scope, conversation):
        return None

    existing = (
        await db.execute(
            select(QualityReview).where(
                QualityReview.message_id == message.id,
                QualityReview.reviewer_version == REVIEWER_VERSION,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status not in {"failed", "skipped"}:
            return existing
        await db.delete(existing)
        await db.flush()

    checks = [name for name, enabled in config.checks.model_dump().items() if enabled]
    review = QualityReview(
        message_id=message.id,
        reviewer_version=REVIEWER_VERSION,
        mode="shadow",
        status="running",
        checks=checks,
        reviewer_model=config.reviewer_model if config.checks.llm else None,
    )
    db.add(review)
    if config.checks.llm and await month_spend(db) >= Decimal(str(config.monthly_budget_usd)):
        review.status = "skipped"
        review.skip_reason = "monthly_budget_reached"
        await db.commit()
        logger.warning("Quality review skipped (monthly budget reached) for %s", message.id)
        return review
    await db.commit()
    review_id = review.id  # still readable after a rollback expires the instance

    started = time.perf_counter()
    details: dict = {}
    try:
        rows: list[QualityFinding] = []
        if config.checks.arithmetic:
            rows += [
                QualityFinding(
                    review_id=review.id,
                    message_id=message.id,
                    check=f.check,
                    kind=f.kind,
                    answer_excerpt=f.answer_excerpt,
                    explanation=f.explanation,
                    proposed_fix=f.proposed_fix,
                    validation="confirmed",
                )
                for f in arithmetic_findings(message.content)
            ]
        if config.checks.citations:
            lookup = article_lookup or _default_article_lookup()
            try:
                citation = await citation_findings(message.content, lookup)
            except Exception as exc:
                details["citations_error"] = type(exc).__name__
                citation = []
            rows += [
                QualityFinding(
                    review_id=review.id,
                    message_id=message.id,
                    check=f.check,
                    kind=f.kind,
                    answer_excerpt=f.answer_excerpt,
                    explanation=f.explanation,
                    validation="confirmed",
                )
                for f in citation
            ]
        if config.checks.llm:
            data = await _review_input(db, message)
            llm = reviewer or _default_reviewer(config.reviewer_model)
            result = await llm.review(data)
            review.cost_usd = result.cost_usd
            details["llm_calls"] = [
                {k: (str(v) if k == "cost_usd" else v) for k, v in c.items() if k != "usage"}
                for c in result.calls
            ]
            details["sources"] = len(data.sources)
            await _log_costs(result.calls, conversation, review.id, llm.model)
            rows += [
                QualityFinding(
                    review_id=review.id,
                    message_id=message.id,
                    check="llm",
                    kind=f.kind,
                    answer_excerpt=f.answer_quote,
                    source_excerpt=f.source_quote or None,
                    source_label=f.source_label,
                    explanation=f.explanation,
                    proposed_fix=f.correction or None,
                    validation=f.validation,
                    validation_reason=f.validation_reason,
                )
                for f in result.findings
            ]
        db.add_all(rows)
        confirmed = [row for row in rows if row.validation == "confirmed"]
        review.status = "flagged" if confirmed else "clean"
        details["findings"] = {
            validation: sum(1 for row in rows if row.validation == validation)
            for validation in {row.validation for row in rows}
        }
        review.details = details
        review.duration_ms = int((time.perf_counter() - started) * 1000)
        await db.commit()
        if confirmed:
            logger.warning(
                "[QUALITY] %d confirmed finding(s) on answer %s", len(confirmed), message.id
            )
        return review
    except Exception as exc:
        await db.rollback()
        review = await db.get(QualityReview, review_id)
        if review is not None:
            review.status = "failed"
            review.error = f"{type(exc).__name__}: {exc}"[:2000]
            review.duration_ms = int((time.perf_counter() - started) * 1000)
            await db.commit()
        logger.exception("Quality review failed for answer %s", message_id)
        return review


async def _log_costs(calls: list[dict], conversation: Conversation, review_id, model: str) -> None:
    from app.services.cost_tracker import cost_tracker

    for call in calls:
        await cost_tracker.log(
            provider="openai",
            model=model,
            operation_type=call["name"],
            tokens_input=call["tokens_input"],
            tokens_output=call["tokens_output"],
            usage=call["usage"],
            organisation_id=str(conversation.organisation_id),
            context_type="quality_review",
            context_id=str(review_id),
        )
