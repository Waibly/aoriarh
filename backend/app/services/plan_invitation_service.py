import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PLAN_FEATURES, TECHNICAL_PLANS
from app.models.account import Account
from app.models.plan_invitation import PlanInvitation, PlanInvitationRedemption
from app.models.user import User
from app.services.plan_service import PlanOverflowError, assign_plan, notify_plan_assignment


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_expired(expires_at: datetime) -> bool:
    now = _utcnow()
    if expires_at.tzinfo is None:
        return expires_at < now.replace(tzinfo=None)
    return expires_at < now


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class PlanInvitationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        label: str,
        plan: str,
        duration_months: int,
        created_by: uuid.UUID,
        email: str | None = None,
        max_uses: int | None = None,
        expires_in_days: int = 30,
    ) -> PlanInvitation:
        if plan not in TECHNICAL_PLANS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Plan '{plan}' non supporté pour les invitations",
            )
        if duration_months < 1 or duration_months > 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La durée doit être entre 1 et 12 mois",
            )

        invitation = PlanInvitation(
            label=label,
            plan=plan,
            duration_months=duration_months,
            created_by=created_by,
            email=email.lower().strip() if email else None,
            max_uses=max_uses,
            expires_at=_utcnow() + timedelta(days=expires_in_days),
        )
        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def validate_token(self, token: uuid.UUID) -> dict:
        result = await self.db.execute(select(PlanInvitation).where(PlanInvitation.token == token))
        invitation = result.scalar_one_or_none()
        if not invitation:
            return {"valid": False, "reason": "not_found"}

        if invitation.status != "active":
            return {"valid": False, "reason": invitation.status}

        if _is_expired(invitation.expires_at):
            invitation.status = "expired"
            await self.db.commit()
            return {"valid": False, "reason": "expired"}

        if invitation.max_uses is not None and invitation.use_count >= invitation.max_uses:
            invitation.status = "exhausted"
            await self.db.commit()
            return {"valid": False, "reason": "exhausted"}

        return {
            "valid": True,
            "plan": invitation.plan,
            "duration_months": invitation.duration_months,
            "label": invitation.label,
            "email": invitation.email,
            "features": PLAN_FEATURES.get(invitation.plan, []),
        }

    async def redeem(self, token: uuid.UUID, user: User) -> dict:
        invitation = await self.db.scalar(
            select(PlanInvitation)
            .where(PlanInvitation.token == token)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Ce lien d'invitation n'existe pas",
            )

        if invitation.email and user.email.lower() != invitation.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ce lien est réservé à une autre adresse email",
            )

        account = await self.db.scalar(
            select(Account)
            .where(Account.owner_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vous devez d'abord créer un compte pour activer ce plan",
            )

        # A previous beneficiary can recover their receipt even after exhaustion,
        # expiration or revocation. This never grants or extends access again.
        existing = await self.db.execute(
            select(PlanInvitationRedemption).where(
                PlanInvitationRedemption.plan_invitation_id == invitation.id,
                PlanInvitationRedemption.account_id == account.id,
            )
        )
        if existing.scalar_one_or_none():
            response = {
                "status": "already_redeemed",
                "message": "Ce lien a déjà été activé sur votre compte.",
                "plan": account.plan,
                "plan_expires_at": account.plan_expires_at,
            }
            await self.db.commit()
            return response

        if invitation.status != "active" or _is_expired(invitation.expires_at):
            raise HTTPException(410, "Ce lien n'est plus disponible pour une nouvelle activation")

        from app.models.subscription import Subscription

        subscription = await self.db.scalar(
            select(Subscription.id)
            .where(
                Subscription.account_id == account.id,
                Subscription.status.in_(["active", "trialing", "past_due"]),
            )
            .limit(1)
        )
        if subscription is not None:
            await self.db.commit()
            return {
                "status": "already_paid",
                "message": "Votre compte a déjà un abonnement payant actif",
            }

        # Reserve the last use with a conditional SQL increment as well as the
        # row lock: the cap cannot be exceeded and rolls back with plan changes.
        reserved = await self.db.execute(
            update(PlanInvitation)
            .where(
                PlanInvitation.id == invitation.id,
                PlanInvitation.status == "active",
                PlanInvitation.expires_at > _utcnow(),
                or_(
                    PlanInvitation.max_uses.is_(None),
                    PlanInvitation.use_count < PlanInvitation.max_uses,
                ),
            )
            .values(
                use_count=PlanInvitation.use_count + 1,
                status=case(
                    (PlanInvitation.use_count + 1 >= PlanInvitation.max_uses, "exhausted"),
                    else_="active",
                ),
            )
            .execution_options(synchronize_session=False)
        )
        if reserved.rowcount != 1:
            await self.db.rollback()
            raise HTTPException(410, "Ce lien a atteint sa limite d'utilisations ou a expiré")
        previous_invite_end = account.plan_expires_at if account.plan == "invite" else None
        try:
            account = await assign_plan(
                self.db, account.id, invitation.plan, invitation.duration_months, commit=False
            )
            # A shorter link must never cut an offer already running.
            if (
                previous_invite_end is not None
                and account.plan == "invite"
                and account.plan_expires_at is not None
                and not _is_expired(previous_invite_end)
                and _as_utc(previous_invite_end) > _as_utc(account.plan_expires_at)
            ):
                account.plan_expires_at = previous_invite_end
            self.db.add(
                PlanInvitationRedemption(
                    plan_invitation_id=invitation.id,
                    account_id=account.id,
                    user_id=user.id,
                    redeemed_at=_utcnow(),
                )
            )
            await self.db.commit()
            await self.db.refresh(invitation)
        except PlanOverflowError as exc:
            await self.db.rollback()
            raise HTTPException(409, "Ce plan ne peut pas contenir vos données actuelles") from exc
        except Exception:
            await self.db.rollback()
            raise

        await notify_plan_assignment(self.db, account)

        return {
            "status": "redeemed",
            "message": "Plan activé avec succès",
            "plan": account.plan,
            "plan_expires_at": account.plan_expires_at,
        }

    async def list_all(
        self, page: int = 1, page_size: int = 20, status_filter: str | None = None
    ) -> tuple[list[PlanInvitation], int]:
        query = select(PlanInvitation)
        count_query = select(func.count()).select_from(PlanInvitation)

        if status_filter:
            query = query.where(PlanInvitation.status == status_filter)
            count_query = count_query.where(PlanInvitation.status == status_filter)

        total = int((await self.db.execute(count_query)).scalar() or 0)

        result = await self.db.execute(
            query.order_by(PlanInvitation.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_detail(self, invitation_id: uuid.UUID) -> dict:
        result = await self.db.execute(
            select(PlanInvitation).where(PlanInvitation.id == invitation_id)
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation non trouvée",
            )

        redemptions_result = await self.db.execute(
            select(PlanInvitationRedemption)
            .where(PlanInvitationRedemption.plan_invitation_id == invitation.id)
            .order_by(PlanInvitationRedemption.redeemed_at.desc())
        )
        redemptions = []
        for r in redemptions_result.scalars().all():
            user = await self.db.get(User, r.user_id)
            redemptions.append(
                {
                    "id": r.id,
                    "account_id": r.account_id,
                    "user_id": r.user_id,
                    "user_email": user.email if user else None,
                    "user_name": user.full_name if user else None,
                    "redeemed_at": r.redeemed_at,
                }
            )

        return {
            "invitation": invitation,
            "redemptions": redemptions,
        }

    async def revoke(self, invitation_id: uuid.UUID) -> PlanInvitation:
        result = await self.db.execute(
            select(PlanInvitation).where(PlanInvitation.id == invitation_id)
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitation non trouvée",
            )
        if invitation.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Impossible de révoquer : statut actuel = {invitation.status}",
            )
        invitation.status = "revoked"
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    def build_shareable_url(self, invitation: PlanInvitation) -> str:
        return f"{settings.frontend_url}/promo/{invitation.token}"
