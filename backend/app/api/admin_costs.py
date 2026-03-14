import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, case, distinct, literal
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import status

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.api_usage import ApiPricing, ApiUsageLog
from app.models.user import User
from app.services.cost_tracker import PRICING

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Schemas ---


class CostSummary(BaseModel):
    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    total_calls: int
    avg_cost_per_question: float
    avg_cost_per_ingestion: float
    total_questions: int
    total_ingestions: int


class CostByPeriod(BaseModel):
    period: str
    cost_usd: float
    tokens_input: int
    tokens_output: int
    calls: int


class CostByProvider(BaseModel):
    provider: str
    model: str
    operation_type: str
    cost_usd: float
    tokens_input: int
    tokens_output: int
    calls: int


class CostByOrganisation(BaseModel):
    organisation_id: str | None
    organisation_name: str | None
    cost_usd: float
    total_questions: int
    total_ingestions: int
    calls: int


class CostByUser(BaseModel):
    user_id: str | None
    user_email: str | None
    cost_usd: float
    total_questions: int
    calls: int


class PricingEntry(BaseModel):
    provider: str
    model: str
    price_input_per_million: float
    price_output_per_million: float | None


class CostDashboard(BaseModel):
    summary: CostSummary
    by_period: list[CostByPeriod]
    by_provider: list[CostByProvider]
    by_organisation: list[CostByOrganisation]
    by_user: list[CostByUser]
    pricing: list[PricingEntry]


# --- Helpers ---


def _period_trunc(granularity: str):
    """Return a SQL expression for date truncation."""
    if granularity == "day":
        return func.date_trunc("day", ApiUsageLog.created_at)
    elif granularity == "week":
        return func.date_trunc("week", ApiUsageLog.created_at)
    elif granularity == "month":
        return func.date_trunc("month", ApiUsageLog.created_at)
    elif granularity == "year":
        return func.date_trunc("year", ApiUsageLog.created_at)
    return func.date_trunc("day", ApiUsageLog.created_at)


# --- Endpoints ---


@router.get("/dashboard", response_model=CostDashboard)
async def get_cost_dashboard(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    granularity: str = Query("day", regex="^(day|week|month|year)$"),
    organisation_id: str | None = Query(None),
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CostDashboard:
    """Full cost dashboard for admin."""
    # Default: last 30 days
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=30)

    # Base filter
    filters = [
        ApiUsageLog.created_at >= datetime.combine(date_from, datetime.min.time()),
        ApiUsageLog.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()),
    ]
    if organisation_id:
        filters.append(ApiUsageLog.organisation_id == organisation_id)

    # 1. Summary
    summary_q = await db.execute(
        select(
            func.coalesce(func.sum(ApiUsageLog.cost_usd), 0).label("total_cost"),
            func.coalesce(func.sum(ApiUsageLog.tokens_input), 0).label("total_in"),
            func.coalesce(func.sum(ApiUsageLog.tokens_output), 0).label("total_out"),
            func.count(ApiUsageLog.id).label("total_calls"),
            func.count(distinct(
                case(
                    (ApiUsageLog.context_type == "question", ApiUsageLog.context_id),
                )
            )).label("total_questions"),
            func.count(distinct(
                case(
                    (ApiUsageLog.context_type == "ingestion", ApiUsageLog.context_id),
                )
            )).label("total_ingestions"),
            func.coalesce(
                func.sum(
                    case(
                        (ApiUsageLog.context_type == "question", ApiUsageLog.cost_usd),
                        else_=0,
                    )
                ), 0
            ).label("question_cost"),
            func.coalesce(
                func.sum(
                    case(
                        (ApiUsageLog.context_type == "ingestion", ApiUsageLog.cost_usd),
                        else_=0,
                    )
                ), 0
            ).label("ingestion_cost"),
        ).where(*filters)
    )
    row = summary_q.one()
    total_questions = row.total_questions or 0
    total_ingestions = row.total_ingestions or 0

    summary = CostSummary(
        total_cost_usd=float(row.total_cost),
        total_tokens_input=int(row.total_in),
        total_tokens_output=int(row.total_out),
        total_calls=int(row.total_calls),
        avg_cost_per_question=float(row.question_cost) / total_questions if total_questions else 0,
        avg_cost_per_ingestion=float(row.ingestion_cost) / total_ingestions if total_ingestions else 0,
        total_questions=total_questions,
        total_ingestions=total_ingestions,
    )

    # 2. By period
    period_col = _period_trunc(granularity)
    period_q = await db.execute(
        select(
            period_col.label("period"),
            func.sum(ApiUsageLog.cost_usd).label("cost"),
            func.sum(ApiUsageLog.tokens_input).label("tokens_in"),
            func.sum(ApiUsageLog.tokens_output).label("tokens_out"),
            func.count(ApiUsageLog.id).label("calls"),
        )
        .where(*filters)
        .group_by("period")
        .order_by("period")
    )
    by_period = [
        CostByPeriod(
            period=r.period.isoformat() if r.period else "",
            cost_usd=float(r.cost or 0),
            tokens_input=int(r.tokens_in or 0),
            tokens_output=int(r.tokens_out or 0),
            calls=int(r.calls or 0),
        )
        for r in period_q.all()
    ]

    # 3. By provider/model/operation
    provider_q = await db.execute(
        select(
            ApiUsageLog.provider,
            ApiUsageLog.model,
            ApiUsageLog.operation_type,
            func.sum(ApiUsageLog.cost_usd).label("cost"),
            func.sum(ApiUsageLog.tokens_input).label("tokens_in"),
            func.sum(ApiUsageLog.tokens_output).label("tokens_out"),
            func.count(ApiUsageLog.id).label("calls"),
        )
        .where(*filters)
        .group_by(ApiUsageLog.provider, ApiUsageLog.model, ApiUsageLog.operation_type)
        .order_by(func.sum(ApiUsageLog.cost_usd).desc())
    )
    by_provider = [
        CostByProvider(
            provider=r.provider,
            model=r.model,
            operation_type=r.operation_type,
            cost_usd=float(r.cost or 0),
            tokens_input=int(r.tokens_in or 0),
            tokens_output=int(r.tokens_out or 0),
            calls=int(r.calls or 0),
        )
        for r in provider_q.all()
    ]

    # 4. By organisation
    from app.models.organisation import Organisation

    # Use snapshot as fallback when org/user has been deleted
    org_name_col = func.coalesce(
        Organisation.name,
        func.max(ApiUsageLog.organisation_name_snapshot),
    ).label("org_name")

    org_q = await db.execute(
        select(
            ApiUsageLog.organisation_id,
            org_name_col,
            func.sum(ApiUsageLog.cost_usd).label("cost"),
            func.count(distinct(
                case(
                    (ApiUsageLog.context_type == "question", ApiUsageLog.context_id),
                )
            )).label("questions"),
            func.count(distinct(
                case(
                    (ApiUsageLog.context_type == "ingestion", ApiUsageLog.context_id),
                )
            )).label("ingestions"),
            func.count(ApiUsageLog.id).label("calls"),
        )
        .outerjoin(Organisation, Organisation.id == ApiUsageLog.organisation_id)
        .where(*filters)
        .group_by(ApiUsageLog.organisation_id, Organisation.name)
        .order_by(func.sum(ApiUsageLog.cost_usd).desc())
    )
    by_organisation = [
        CostByOrganisation(
            organisation_id=str(r.organisation_id) if r.organisation_id else None,
            organisation_name=r.org_name if r.org_name else "Organisation supprimée",
            cost_usd=float(r.cost or 0),
            total_questions=int(r.questions or 0),
            total_ingestions=int(r.ingestions or 0),
            calls=int(r.calls or 0),
        )
        for r in org_q.all()
    ]

    # 5. By user — use snapshot as fallback for deleted users
    user_email_col = func.coalesce(
        User.email,
        func.max(ApiUsageLog.user_email_snapshot),
    ).label("user_email")

    user_q = await db.execute(
        select(
            ApiUsageLog.user_id,
            user_email_col,
            func.sum(ApiUsageLog.cost_usd).label("cost"),
            func.count(distinct(
                case(
                    (ApiUsageLog.context_type == "question", ApiUsageLog.context_id),
                )
            )).label("questions"),
            func.count(ApiUsageLog.id).label("calls"),
        )
        .outerjoin(User, User.id == ApiUsageLog.user_id)
        .where(*filters)
        .group_by(ApiUsageLog.user_id, User.email)
        .order_by(func.sum(ApiUsageLog.cost_usd).desc())
        .limit(50)
    )
    by_user = [
        CostByUser(
            user_id=str(r.user_id) if r.user_id else None,
            user_email=r.user_email if r.user_email else "Utilisateur supprimé",
            cost_usd=float(r.cost or 0),
            total_questions=int(r.questions or 0),
            calls=int(r.calls or 0),
        )
        for r in user_q.all()
    ]

    # 6. Current pricing
    pricing = [
        PricingEntry(
            provider=k[0],
            model=k[1],
            price_input_per_million=v[0],
            price_output_per_million=v[1],
        )
        for k, v in PRICING.items()
    ]

    return CostDashboard(
        summary=summary,
        by_period=by_period,
        by_provider=by_provider,
        by_organisation=by_organisation,
        by_user=by_user,
        pricing=pricing,
    )


class PricingUpdate(BaseModel):
    provider: str
    model: str
    price_input_per_million: float
    price_output_per_million: float | None = None


@router.put("/pricing", response_model=list[PricingEntry], status_code=status.HTTP_200_OK)
async def update_pricing(
    entries: list[PricingUpdate],
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[PricingEntry]:
    """Update pricing in-memory and in database."""
    for entry in entries:
        key = (entry.provider, entry.model)
        # Update in-memory pricing
        PRICING[key] = (entry.price_input_per_million, entry.price_output_per_million)
        # Update in database
        result = await db.execute(
            select(ApiPricing).where(
                ApiPricing.provider == entry.provider,
                ApiPricing.model == entry.model,
                ApiPricing.effective_to.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.price_input_per_million = entry.price_input_per_million
            row.price_output_per_million = entry.price_output_per_million
        else:
            db.add(ApiPricing(
                provider=entry.provider,
                model=entry.model,
                price_input_per_million=entry.price_input_per_million,
                price_output_per_million=entry.price_output_per_million,
            ))

    await db.commit()
    logger.info("Pricing updated: %s", [(e.provider, e.model) for e in entries])

    return [
        PricingEntry(
            provider=k[0],
            model=k[1],
            price_input_per_million=v[0],
            price_output_per_million=v[1],
        )
        for k, v in PRICING.items()
    ]
