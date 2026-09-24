"""Single source of truth for organisation context inherited by conversations."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ccn import CcnReference, OrganisationConvention
from app.models.organisation import Organisation


async def load_organisation_context(
    db: AsyncSession, organisation_id: uuid.UUID
) -> dict[str, str | bool | None] | None:
    """Return the live organisation profile used by chat and case files."""
    result = await db.execute(select(Organisation).where(Organisation.id == organisation_id))
    org = result.scalar_one_or_none()
    if org is None:
        return None

    ccn_result = await db.execute(
        select(OrganisationConvention.idcc, CcnReference.titre)
        .join(CcnReference, CcnReference.idcc == OrganisationConvention.idcc)
        .where(
            OrganisationConvention.organisation_id == organisation_id,
            OrganisationConvention.status.in_(["ready", "indexing", "fetching"]),
        )
    )
    installed_ccns = ccn_result.all()

    if installed_ccns:
        convention_str = "; ".join(f"{row.titre} (IDCC {row.idcc})" for row in installed_ccns)
    else:
        convention_str = org.convention_collective

    return {
        "nom": org.name,
        "forme_juridique": org.forme_juridique,
        "taille": org.taille,
        "convention_collective": convention_str,
        "secteur_activite": org.secteur_activite,
        "not_subject_to_ccn": bool(org.not_subject_to_ccn),
    }
