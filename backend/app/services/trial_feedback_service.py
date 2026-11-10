"""Questionnaire de fin d'essai : raisons proposées, liens signés, enregistrement.

Le lien envoyé par email identifie le compte par un identifiant signé (HMAC),
sans connexion. La raison cliquée n'est qu'une présélection : la réponse est
enregistrée uniquement à l'envoi du formulaire (POST), pour qu'un scanner
d'emails qui ouvre les liens n'enregistre pas de fausse réponse.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.account import Account
from app.models.monthly_question_usage import MonthlyQuestionUsage
from app.models.trial_feedback import TrialFeedback

COMMENT_MAX_LENGTH = 2000

# Jours après la fin de l'essai (non converti) où partent les emails.
FEEDBACK_EMAIL_DAY = 3
DELETION_WARNING_EMAIL_DAY = 23


@dataclass(frozen=True)
class TrialFeedbackReason:
    code: str
    label: str
    question: str


REASONS: tuple[TrialFeedbackReason, ...] = (
    TrialFeedbackReason("prix", "Le prix", "Quel budget vous paraîtrait adapté ?"),
    TrialFeedbackReason(
        "pas_le_temps",
        "Je n'ai pas eu le temps de tester",
        "Qu'auriez-vous voulu tester ?",
    ),
    TrialFeedbackReason(
        "besoin",
        "L'outil ne répond pas à mon besoin",
        "Qu'est-ce qui vous a manqué ?",
    ),
    TrialFeedbackReason(
        "plus_tard",
        "Je souscrirai plus tard",
        "Qu'est-ce qui vous ferait souscrire ?",
    ),
    TrialFeedbackReason("autre", "Autre raison", "Laquelle ?"),
)
REASONS_BY_CODE = {r.code: r for r in REASONS}


def feedback_signature(account_id: uuid.UUID) -> str:
    return hmac.new(
        settings.secret_key.encode(),
        f"trial-feedback:{account_id}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def verify_feedback_signature(account_id: uuid.UUID, sig: str | None) -> bool:
    return bool(sig) and hmac.compare_digest(feedback_signature(account_id), sig)


def feedback_url(account_id: uuid.UUID, reason: str | None = None) -> str:
    params = {"a": str(account_id), "sig": feedback_signature(account_id)}
    if reason:
        params["r"] = reason
    return f"{settings.api_base_url.rstrip('/')}/api/v1/trial-feedback?{urlencode(params)}"


async def questions_used_by_account(db: AsyncSession, account_id: uuid.UUID) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(MonthlyQuestionUsage.questions_used), 0)).where(
            MonthlyQuestionUsage.account_id == account_id
        )
    )
    return int(total or 0)


async def record_feedback(
    db: AsyncSession,
    account: Account,
    reason: str,
    comment: str | None,
) -> TrialFeedback:
    """Create or replace the account's answer. Raises ValueError on invalid input."""
    if reason not in REASONS_BY_CODE:
        raise ValueError("Raison inconnue")
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > COMMENT_MAX_LENGTH:
        raise ValueError(f"Le commentaire dépasse {COMMENT_MAX_LENGTH} caractères")

    questions_used = await questions_used_by_account(db, account.id)
    feedback = (
        await db.execute(select(TrialFeedback).where(TrialFeedback.account_id == account.id))
    ).scalar_one_or_none()
    if feedback is None:
        feedback = TrialFeedback(account_id=account.id)
        db.add(feedback)
    feedback.reason = reason
    feedback.comment = comment
    feedback.questions_used = questions_used
    feedback.trial_ended_at = account.plan_expires_at if account.plan == "gratuit" else None
    feedback.responded_at = datetime.now(UTC)
    await db.commit()
    return feedback
