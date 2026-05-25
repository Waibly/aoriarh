import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PLAN_FEATURES, TECHNICAL_PLANS
from app.models.plan_invitation import PlanInvitation, PlanInvitationRedemption
from app.models.user import User
from app.services.plan_service import assign_plan


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_expired(expires_at: datetime) -> bool:
    now = _utcnow()
    if expires_at.tzinfo is None:
        return expires_at < now.replace(tzinfo=None)
    return expires_at < now


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
        result = await self.db.execute(
            select(PlanInvitation).where(PlanInvitation.token == token)
        )
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
        validation = await self.validate_token(token)
        if not validation["valid"]:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"Ce lien n'est plus valide ({validation['reason']})",
            )

        result = await self.db.execute(
            select(PlanInvitation).where(PlanInvitation.token == token)
        )
        invitation = result.scalar_one()

        if invitation.email and user.email.lower() != invitation.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ce lien est réservé à une autre adresse email",
            )

        account = user.owned_account
        if not account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vous devez d'abord créer un compte pour activer ce plan",
            )

        # Already on a commercial plan with active Stripe subscription
        from app.models.subscription import Subscription
        sub_result = await self.db.execute(
            select(Subscription).where(
                Subscription.account_id == account.id,
                Subscription.status.in_(["active", "trialing", "past_due"]),
            )
        )
        if sub_result.scalar_one_or_none():
            return {
                "status": "already_paid",
                "message": "Votre compte a déjà un abonnement payant actif",
            }

        # Already redeemed this specific link
        existing = await self.db.execute(
            select(PlanInvitationRedemption).where(
                PlanInvitationRedemption.plan_invitation_id == invitation.id,
                PlanInvitationRedemption.account_id == account.id,
            )
        )
        if existing.scalar_one_or_none():
            return {
                "status": "already_redeemed",
                "message": "Vous avez déjà activé ce lien",
            }

        account = await assign_plan(
            self.db, account.id, invitation.plan, invitation.duration_months
        )

        redemption = PlanInvitationRedemption(
            plan_invitation_id=invitation.id,
            account_id=account.id,
            user_id=user.id,
            redeemed_at=_utcnow(),
        )
        self.db.add(redemption)

        invitation.use_count += 1
        if invitation.max_uses is not None and invitation.use_count >= invitation.max_uses:
            invitation.status = "exhausted"

        await self.db.commit()

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
            redemptions.append({
                "id": r.id,
                "account_id": r.account_id,
                "user_id": r.user_id,
                "user_email": user.email if user else None,
                "user_name": user.full_name if user else None,
                "redeemed_at": r.redeemed_at,
            })

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
