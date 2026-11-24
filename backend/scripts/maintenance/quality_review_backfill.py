"""Run the automated quality review on past answers (shadow: recorded, nobody alerted).

Used to measure real errors and false alarms before relying on the review. Paid:
each reviewed answer costs model calls. Without --run, only counts and estimates.

Inside the backend container:
  python -m scripts.maintenance.quality_review_backfill --since 2026-11-01 --limit 50
  python -m scripts.maintenance.quality_review_backfill --since 2026-11-01 --limit 50 --run
  python -m scripts.maintenance.quality_review_backfill --message-id <uuid> --run
"""

import argparse
import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.models.conversation import Conversation, Message
from app.models.quality_review import QualityFinding, QualityReview
from app.models.user import User
from app.services.platform_settings import get_quality_review_settings
from app.services.quality_review.service import REVIEWER_VERSION, run_quality_review

ESTIMATED_COST_USD = Decimal("0.08")


async def candidates(args) -> list[uuid.UUID]:
    async with async_session_factory() as db:
        if args.message_id:
            return [uuid.UUID(args.message_id)]
        reviewed = select(QualityReview.message_id).where(
            QualityReview.reviewer_version == REVIEWER_VERSION,
            QualityReview.status.in_(["clean", "flagged"]),
        )
        query = (
            select(Message.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(User, User.id == Conversation.user_id)
            .where(
                Message.role == "assistant",
                Message.created_at >= args.since,
                Message.id.not_in(reviewed),
                func.length(Message.content) > 200,
            )
            .order_by(Message.created_at.desc())
            .limit(args.limit)
        )
        if not args.include_staff:
            query = query.where(User.role != "admin")
        return list((await db.execute(query)).scalars())


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=lambda v: datetime.fromisoformat(v).replace(tzinfo=UTC))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--message-id")
    parser.add_argument("--include-staff", action="store_true")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--budget", type=float, help="Monthly budget for this run (USD)")
    parser.add_argument("--run", action="store_true", help="Actually call the models (paid)")
    args = parser.parse_args()
    if not args.message_id and not args.since:
        parser.error("--since or --message-id is required")

    ids = await candidates(args)
    print(f"{len(ids)} answer(s) to review, estimated ~{ESTIMATED_COST_USD * len(ids):.2f} USD")
    if not args.run or not ids:
        return

    async with async_session_factory() as db:
        config = await get_quality_review_settings(db, use_cache=False)
    if args.budget is not None:
        config = config.model_copy(update={"monthly_budget_usd": args.budget})

    semaphore = asyncio.Semaphore(args.concurrency)
    totals: dict[str, int] = {}
    spent = Decimal(0)

    async def one(message_id: uuid.UUID) -> None:
        nonlocal spent
        async with semaphore, async_session_factory() as db:
            review = await run_quality_review(db, message_id, force=True, config=config)
            status = review.status if review else "not_reviewed"
            totals[status] = totals.get(status, 0) + 1
            if review is not None:
                spent += Decimal(review.cost_usd or 0)
                findings = (
                    await db.execute(
                        select(QualityFinding.validation, QualityFinding.kind).where(
                            QualityFinding.review_id == review.id
                        )
                    )
                ).all()
                summary = ", ".join(f"{kind}:{validation}" for validation, kind in findings)
                print(f"{message_id} {status} {review.cost_usd} USD {summary}", flush=True)

    await asyncio.gather(*(one(message_id) for message_id in ids))
    print(f"Done: {totals}, spent {spent:.4f} USD")


if __name__ == "__main__":
    asyncio.run(main())
