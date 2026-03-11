import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_admin_action(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    organisation_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    details: str | None = None,
) -> None:
    """Log an admin action to the audit trail."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        organisation_id=organisation_id,
        ip_address=ip_address,
        details=details,
    )
    db.add(entry)
    await db.flush()
