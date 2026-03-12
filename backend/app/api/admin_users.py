from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.user import User
from app.models.membership import Membership
from app.models.organisation import Organisation

router = APIRouter()


class UserOrgItem(BaseModel):
    model_config = {"from_attributes": True}
    organisation_id: str
    organisation_name: str
    role_in_org: str


class AdminUserItem(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: str
    organisations: list[UserOrgItem]


class UserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int
    page: int
    page_size: int


@router.get("/", response_model=UserListResponse)
async def list_users(
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: str | None = Query(None),
) -> UserListResponse:
    """List all users with their organisations."""
    base = select(User)
    count_base = select(func.count()).select_from(User)

    if search:
        pattern = f"%{search}%"
        base = base.where(User.email.ilike(pattern) | User.full_name.ilike(pattern))
        count_base = count_base.where(
            User.email.ilike(pattern) | User.full_name.ilike(pattern)
        )

    total = (await db.execute(count_base)).scalar() or 0

    offset = (page - 1) * page_size
    stmt = (
        base.options(
            selectinload(User.memberships).selectinload(Membership.organisation)
        )
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    users = result.scalars().all()

    items: list[AdminUserItem] = []
    for u in users:
        orgs = [
            UserOrgItem(
                organisation_id=str(m.organisation_id),
                organisation_name=m.organisation.name if m.organisation else "—",
                role_in_org=m.role_in_org,
            )
            for m in u.memberships
        ]
        items.append(
            AdminUserItem(
                id=str(u.id),
                email=u.email,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                created_at=u.created_at.isoformat(),
                organisations=orgs,
            )
        )

    return UserListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
