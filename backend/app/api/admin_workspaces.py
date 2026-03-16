"""Admin endpoint for workspace/client overview."""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, distinct, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.api_usage import ApiUsageLog
from app.models.document import Document
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class WorkspaceMember(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str  # global role
    role_in_workspace: str  # role in account_member
    is_owner: bool


class WorkspaceOrg(BaseModel):
    id: str
    name: str
    documents_count: int
    members_count: int


class WorkspaceOverview(BaseModel):
    account_id: str
    name: str
    plan: str
    plan_expires_at: str | None
    created_at: str
    owner_email: str
    owner_name: str
    organisations: list[WorkspaceOrg]
    members: list[WorkspaceMember]
    total_documents: int
    total_questions: int


class OrphanUser(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    created_at: str


class WorkspacesResponse(BaseModel):
    workspaces: list[WorkspaceOverview]
    orphan_users: list[OrphanUser]
    totals: dict


@router.get("/", response_model=WorkspacesResponse)
async def list_workspaces(
    search: str | None = Query(None),
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> WorkspacesResponse:
    """List all workspaces with their orgs, members, and usage stats."""

    # 1. Fetch all accounts with owners
    accounts_q = await db.execute(
        select(Account)
        .options(selectinload(Account.owner))
        .order_by(Account.created_at.desc())
    )
    accounts = list(accounts_q.scalars().all())

    workspaces: list[WorkspaceOverview] = []

    for account in accounts:
        owner = account.owner
        if not owner:
            continue

        # Search filter
        if search:
            q = search.lower()
            match = (
                q in account.name.lower()
                or q in owner.email.lower()
                or q in owner.full_name.lower()
            )
            if not match:
                # Check org names
                orgs_check = await db.execute(
                    select(Organisation.name).where(Organisation.account_id == account.id)
                )
                org_names = [r[0].lower() for r in orgs_check.all()]
                if not any(q in name for name in org_names):
                    # Check member emails
                    members_check = await db.execute(
                        select(User.email).join(AccountMember, AccountMember.user_id == User.id)
                        .where(AccountMember.account_id == account.id)
                    )
                    member_emails = [r[0].lower() for r in members_check.all()]
                    if not any(q in email for email in member_emails):
                        continue

        # Organisations
        orgs_q = await db.execute(
            select(Organisation).where(Organisation.account_id == account.id)
        )
        orgs = list(orgs_q.scalars().all())

        org_items: list[WorkspaceOrg] = []
        total_docs = 0
        for org in orgs:
            # Doc count
            doc_count_q = await db.execute(
                select(func.count(Document.id)).where(Document.organisation_id == org.id)
            )
            doc_count = doc_count_q.scalar() or 0
            total_docs += doc_count

            # Member count
            member_count_q = await db.execute(
                select(func.count(Membership.id)).where(Membership.organisation_id == org.id)
            )
            member_count = member_count_q.scalar() or 0

            org_items.append(WorkspaceOrg(
                id=str(org.id),
                name=org.name,
                documents_count=doc_count,
                members_count=member_count,
            ))

        # Members (account_members + owner)
        am_q = await db.execute(
            select(AccountMember)
            .options(selectinload(AccountMember.user))
            .where(AccountMember.account_id == account.id)
        )
        account_members = list(am_q.scalars().all())

        member_items: list[WorkspaceMember] = []
        # Add owner first
        member_items.append(WorkspaceMember(
            user_id=str(owner.id),
            email=owner.email,
            full_name=owner.full_name,
            role=owner.role,
            role_in_workspace="owner",
            is_owner=True,
        ))
        # Add other members
        seen_ids = {str(owner.id)}
        for am in account_members:
            uid = str(am.user_id)
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            u = am.user
            if u:
                member_items.append(WorkspaceMember(
                    user_id=uid,
                    email=u.email,
                    full_name=u.full_name,
                    role=u.role,
                    role_in_workspace=am.role_in_org,
                    is_owner=False,
                ))

        # Question count
        question_q = await db.execute(
            select(func.count(distinct(ApiUsageLog.context_id))).where(
                ApiUsageLog.context_type == "question",
                ApiUsageLog.organisation_id.in_([o.id for o in orgs]) if orgs else ApiUsageLog.id.is_(None),
            )
        )
        total_questions = question_q.scalar() or 0

        workspaces.append(WorkspaceOverview(
            account_id=str(account.id),
            name=account.name,
            plan=account.plan,
            plan_expires_at=account.plan_expires_at.isoformat() if account.plan_expires_at else None,
            created_at=account.created_at.isoformat() if hasattr(account, 'created_at') and account.created_at else "",
            owner_email=owner.email,
            owner_name=owner.full_name,
            organisations=org_items,
            members=member_items,
            total_documents=total_docs,
            total_questions=total_questions,
        ))

    # 2. Orphan users (no owned_account, no account_memberships)
    orphan_q = await db.execute(
        select(User).where(
            User.role != "admin",
            ~User.id.in_(select(Account.owner_id)),
            ~User.id.in_(select(AccountMember.user_id)),
        )
    )
    orphans = list(orphan_q.scalars().all())

    if search:
        q = search.lower()
        orphans = [u for u in orphans if q in u.email.lower() or q in u.full_name.lower()]

    orphan_items = [
        OrphanUser(
            user_id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in orphans
    ]

    # 3. Totals
    total_users = await db.execute(select(func.count(User.id)).where(User.role != "admin"))
    total_orgs = await db.execute(select(func.count(Organisation.id)))
    total_docs = await db.execute(select(func.count(Document.id)).where(Document.organisation_id.isnot(None)))

    totals = {
        "users": total_users.scalar() or 0,
        "workspaces": len(accounts),
        "organisations": total_orgs.scalar() or 0,
        "documents": total_docs.scalar() or 0,
    }

    return WorkspacesResponse(
        workspaces=workspaces,
        orphan_users=orphan_items,
        totals=totals,
    )
