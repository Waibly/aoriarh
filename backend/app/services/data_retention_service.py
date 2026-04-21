"""GDPR data retention service.

Implements two capabilities:
  - scheduled purge of accounts that have exceeded their retention window
    (30 days after trial expiry or voluntary cancellation, 60 days after
    payment suspension);
  - ad-hoc export + erasure endpoints driven by the admin on behalf of
    users exercising their GDPR rights (articles 15, 17, 20).

Retention windows are defined in ``app.core.plans``.

Notes on "when did the status change?":
  - For trial expiry we anchor on ``Account.plan_expires_at`` (authoritative).
  - For commercial cancellation / suspension we use ``Account.updated_at``
    as a best-effort approximation. A future migration introducing
    ``Account.status_changed_at`` would make this exact, but ``updated_at``
    is good enough for the retention use-case since accounts in those
    terminal states rarely receive other writes.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import (
    GRACE_AFTER_CANCEL_DAYS,
    GRACE_AFTER_TRIAL_END_DAYS,
    GRACE_AFTER_UNPAID_DAYS,
)
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.ccn import OrganisationConvention
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class PurgeCandidate:
    account_id: uuid.UUID
    account_name: str
    owner_email: str
    reason: str  # "trial_expired" | "canceled" | "unpaid"
    ref_date: datetime  # date from which the retention window started counting
    eligible_since: datetime  # ref_date + grace window


class DataRetentionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Purge candidate resolution
    # ------------------------------------------------------------------

    async def find_candidates(self) -> list[PurgeCandidate]:
        """Return all accounts whose retention window is over."""
        now = datetime.now(UTC)
        candidates: list[PurgeCandidate] = []

        # 1) Trial expired (plan='gratuit' + status='suspended')
        #    → purge 30 days after plan_expires_at.
        trial_cutoff = now - timedelta(days=GRACE_AFTER_TRIAL_END_DAYS)
        result = await self.db.execute(
            select(Account).where(
                Account.plan == "gratuit",
                Account.status == "suspended",
                Account.plan_expires_at.isnot(None),
                Account.plan_expires_at < trial_cutoff,
            )
        )
        for account in result.scalars():
            owner = await self.db.get(User, account.owner_id)
            candidates.append(
                PurgeCandidate(
                    account_id=account.id,
                    account_name=account.name,
                    owner_email=owner.email if owner else "<unknown>",
                    reason="trial_expired",
                    ref_date=account.plan_expires_at,
                    eligible_since=account.plan_expires_at
                    + timedelta(days=GRACE_AFTER_TRIAL_END_DAYS),
                )
            )

        # 2) Voluntary cancellation (status='canceled')
        #    → purge 30 days after updated_at (approximation of status change).
        cancel_cutoff = now - timedelta(days=GRACE_AFTER_CANCEL_DAYS)
        result = await self.db.execute(
            select(Account).where(
                Account.status == "canceled",
                Account.updated_at < cancel_cutoff,
            )
        )
        for account in result.scalars():
            owner = await self.db.get(User, account.owner_id)
            candidates.append(
                PurgeCandidate(
                    account_id=account.id,
                    account_name=account.name,
                    owner_email=owner.email if owner else "<unknown>",
                    reason="canceled",
                    ref_date=account.updated_at,
                    eligible_since=account.updated_at
                    + timedelta(days=GRACE_AFTER_CANCEL_DAYS),
                )
            )

        # 3) Payment failure / unpaid (status='suspended' on a commercial plan)
        #    → purge 60 days after updated_at.
        unpaid_cutoff = now - timedelta(days=GRACE_AFTER_UNPAID_DAYS)
        result = await self.db.execute(
            select(Account).where(
                Account.status == "suspended",
                Account.plan.in_(["solo", "equipe", "groupe"]),
                Account.updated_at < unpaid_cutoff,
            )
        )
        for account in result.scalars():
            owner = await self.db.get(User, account.owner_id)
            candidates.append(
                PurgeCandidate(
                    account_id=account.id,
                    account_name=account.name,
                    owner_email=owner.email if owner else "<unknown>",
                    reason="unpaid",
                    ref_date=account.updated_at,
                    eligible_since=account.updated_at
                    + timedelta(days=GRACE_AFTER_UNPAID_DAYS),
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # Export (GDPR art. 15 / 20)
    # ------------------------------------------------------------------

    async def export_account(self, account_id: uuid.UUID) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of everything we hold about an account."""
        account = await self.db.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")
        owner = await self.db.get(User, account.owner_id)

        # Members
        members_result = await self.db.execute(
            select(AccountMember).where(AccountMember.account_id == account_id)
        )
        members_rows: list[dict] = []
        for m in members_result.scalars():
            u = await self.db.get(User, m.user_id)
            members_rows.append(
                {
                    "member_id": str(m.id),
                    "user_email": u.email if u else None,
                    "role_in_org": m.role_in_org,
                    "joined_at": m.created_at.isoformat() if m.created_at else None,
                }
            )

        # Organisations (and their conventions)
        orgs_result = await self.db.execute(
            select(Organisation).where(Organisation.account_id == account_id)
        )
        orgs_rows: list[dict] = []
        for org in orgs_result.scalars():
            conv_result = await self.db.execute(
                select(OrganisationConvention).where(
                    OrganisationConvention.organisation_id == org.id
                )
            )
            conventions = [
                {"idcc": c.idcc, "status": c.status}
                for c in conv_result.scalars()
            ]
            orgs_rows.append(
                {
                    "id": str(org.id),
                    "name": org.name,
                    "forme_juridique": org.forme_juridique,
                    "taille": org.taille,
                    "secteur_activite": org.secteur_activite,
                    "created_at": org.created_at.isoformat() if org.created_at else None,
                    "conventions": conventions,
                }
            )

        # Conversations + messages (owned by users of this account)
        org_ids = [uuid.UUID(o["id"]) for o in orgs_rows]
        conv_rows: list[dict] = []
        if org_ids:
            conv_result = await self.db.execute(
                select(Conversation).where(Conversation.organisation_id.in_(org_ids))
            )
            for conv in conv_result.scalars():
                msgs_result = await self.db.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.created_at)
                )
                msgs = [
                    {
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in msgs_result.scalars()
                ]
                conv_rows.append(
                    {
                        "id": str(conv.id),
                        "title": conv.title,
                        "organisation_id": str(conv.organisation_id),
                        "created_at": conv.created_at.isoformat() if conv.created_at else None,
                        "messages": msgs,
                    }
                )

        # Documents (metadata only, not the file bytes)
        doc_rows: list[dict] = []
        if org_ids:
            docs_result = await self.db.execute(
                select(Document).where(Document.organisation_id.in_(org_ids))
            )
            doc_rows = [
                {
                    "id": str(d.id),
                    "name": d.name,
                    "source_type": d.source_type,
                    "organisation_id": str(d.organisation_id) if d.organisation_id else None,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in docs_result.scalars()
            ]

        return {
            "exported_at": datetime.now(UTC).isoformat(),
            "account": {
                "id": str(account.id),
                "name": account.name,
                "plan": account.plan,
                "status": account.status,
                "plan_assigned_at": account.plan_assigned_at.isoformat()
                if account.plan_assigned_at else None,
                "plan_expires_at": account.plan_expires_at.isoformat()
                if account.plan_expires_at else None,
                "stripe_customer_id": account.stripe_customer_id,
                "created_at": account.created_at.isoformat() if account.created_at else None,
            },
            "owner": {
                "id": str(owner.id) if owner else None,
                "email": owner.email if owner else None,
                "full_name": owner.full_name if owner else None,
                "role": owner.role if owner else None,
                "profil_metier": owner.profil_metier if owner else None,
            },
            "members": members_rows,
            "organisations": orgs_rows,
            "conversations": conv_rows,
            "documents": doc_rows,
        }

    # ------------------------------------------------------------------
    # Erasure (GDPR art. 17)
    # ------------------------------------------------------------------

    async def purge_account(self, account_id: uuid.UUID) -> dict[str, int]:
        """Delete all personal data for an account.

        Cascades handle subscription-related rows; we explicitly clean
        orphans (org-level data, documents, Qdrant points, MinIO files).

        Returns a summary dict of counts deleted per entity, useful for
        admin logs and compliance trails.
        """
        from app.models.subscription import Subscription
        from app.models.ccn import OrganisationConvention as OrgConv
        from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
        from app.services.storage_service import StorageService
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        account = await self.db.get(Account, account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        summary = {
            "organisations": 0,
            "documents": 0,
            "conversations": 0,
            "messages": 0,
            "invitations": 0,
            "members": 0,
            "memberships": 0,
            "qdrant_collections_cleaned": 0,
            "storage_objects_deleted": 0,
        }

        # List orgs to clean Qdrant + MinIO before DB deletion
        orgs_result = await self.db.execute(
            select(Organisation).where(Organisation.account_id == account_id)
        )
        orgs = list(orgs_result.scalars())
        org_ids = [o.id for o in orgs]

        # Qdrant: remove all points scoped to these organisations
        if org_ids:
            try:
                client = get_qdrant_client()
                for org_id in org_ids:
                    client.delete(
                        collection_name=COLLECTION_NAME,
                        points_selector=FilterSelector(
                            filter=Filter(
                                must=[
                                    FieldCondition(
                                        key="organisation_id",
                                        match=MatchValue(value=str(org_id)),
                                    )
                                ]
                            )
                        ),
                    )
                    summary["qdrant_collections_cleaned"] += 1
            except Exception:
                logger.exception("Purge: Qdrant cleanup failed for account %s", account_id)

        # MinIO: delete every document file owned by these orgs
        if org_ids:
            docs_result = await self.db.execute(
                select(Document).where(Document.organisation_id.in_(org_ids))
            )
            docs = list(docs_result.scalars())
            storage = StorageService()
            for doc in docs:
                try:
                    if doc.storage_path:
                        storage.delete_file(doc.storage_path)
                        summary["storage_objects_deleted"] += 1
                except Exception:
                    logger.exception(
                        "Purge: failed to delete storage object %s for account %s",
                        doc.storage_path, account_id,
                    )

            # Conversations + messages (no cascade from Account)
            if org_ids:
                # Count before delete for the summary
                from sqlalchemy import func as sqlfunc
                count_convs = await self.db.execute(
                    select(sqlfunc.count())
                    .select_from(Conversation)
                    .where(Conversation.organisation_id.in_(org_ids))
                )
                summary["conversations"] = int(count_convs.scalar() or 0)

                count_msgs = await self.db.execute(
                    select(sqlfunc.count())
                    .select_from(Message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(Conversation.organisation_id.in_(org_ids))
                )
                summary["messages"] = int(count_msgs.scalar() or 0)

                # Delete messages first (no cascade guarantee), then conversations.
                conv_ids = (await self.db.execute(
                    select(Conversation.id).where(Conversation.organisation_id.in_(org_ids))
                )).scalars().all()
                if conv_ids:
                    await self.db.execute(
                        delete(Message).where(Message.conversation_id.in_(conv_ids))
                    )
                    await self.db.execute(
                        delete(Conversation).where(Conversation.id.in_(conv_ids))
                    )

            # Documents (DB)
            summary["documents"] = len(docs)
            await self.db.execute(
                delete(Document).where(Document.organisation_id.in_(org_ids))
            )

            # OrganisationConventions, Memberships, Invitations (no cascade on all)
            await self.db.execute(
                delete(OrgConv).where(OrgConv.organisation_id.in_(org_ids))
            )
            memb_result = await self.db.execute(
                select(Membership).where(Membership.organisation_id.in_(org_ids))
            )
            summary["memberships"] = len(list(memb_result.scalars()))
            await self.db.execute(
                delete(Membership).where(Membership.organisation_id.in_(org_ids))
            )

        # Invitations for this account (account-level)
        inv_result = await self.db.execute(
            select(Invitation).where(Invitation.account_id == account_id)
        )
        summary["invitations"] = len(list(inv_result.scalars()))
        await self.db.execute(
            delete(Invitation).where(Invitation.account_id == account_id)
        )

        # Organisations (parent of memberships we just removed)
        summary["organisations"] = len(orgs)
        for org in orgs:
            await self.db.delete(org)

        # Account members (access grants from other users)
        members_result = await self.db.execute(
            select(AccountMember).where(AccountMember.account_id == account_id)
        )
        summary["members"] = len(list(members_result.scalars()))
        await self.db.execute(
            delete(AccountMember).where(AccountMember.account_id == account_id)
        )

        # Account (cascade deletes Subscription, SubscriptionAddon,
        # BoosterPurchase, MonthlyQuestionUsage via the model cascade config).
        owner_id = account.owner_id
        _ = Subscription  # silence unused import, the relationship handles delete
        await self.db.delete(account)

        # Owner user — delete last. Members (other users) are *not* deleted
        # because they may be owners of other accounts.
        owner = await self.db.get(User, owner_id)
        if owner is not None:
            await self.db.delete(owner)

        await self.db.commit()

        logger.info(
            "Purge: account %s deleted — %s",
            account_id, summary,
        )
        return summary
