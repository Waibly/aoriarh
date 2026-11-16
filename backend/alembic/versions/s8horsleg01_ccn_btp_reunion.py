"""Conventions du BTP de La Réunion (0627, 0771, 2389) dans le référentiel

Revision ID: s8horsleg01
Revises: r7territ01
Create Date: 2026-11-16 16:00:00.000000

Leur texte n'est pas sur Légifrance : il est lu depuis
app/reference/ccn_hors_legifrance/ (cf. app/services/ccn_hors_legifrance.py).
Sans identifiant KALI, la relecture mensuelle de la liste les laisse intacts.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s8horsleg01"
down_revision: str | None = "r7territ01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROWS = [
    (
        "0627",
        "Convention collective départementale des employés, techniciens et agents de "
        "maîtrise du bâtiment et des travaux publics de La Réunion du 12 juillet 1971",
        "BTP ETAM de La Réunion",
    ),
    (
        "0771",
        "Convention collective départementale des ingénieurs assimilés et cadres du "
        "bâtiment et des travaux publics de La Réunion du 9 mai 1974",
        "BTP ingénieurs et cadres de La Réunion",
    ),
    (
        "2389",
        "Convention collective régionale des ouvriers du bâtiment et des travaux "
        "publics de La Réunion du 13 mai 2004",
        "BTP ouvriers de La Réunion",
    ),
]


def upgrade() -> None:
    for idcc, titre, titre_court in _ROWS:
        op.get_bind().execute(
            sa.text(
                "INSERT INTO ccn_reference (idcc, titre, titre_court, kali_id, etat) "
                "VALUES (:idcc, :titre, :titre_court, NULL, 'VIGUEUR_ETEN') "
                "ON CONFLICT (idcc) DO UPDATE SET titre = EXCLUDED.titre, "
                "titre_court = EXCLUDED.titre_court, etat = EXCLUDED.etat"
            ),
            {"idcc": idcc, "titre": titre, "titre_court": titre_court},
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM ccn_reference WHERE idcc IN ('0627', '0771', '2389') "
            "AND kali_id IS NULL AND NOT EXISTS (SELECT 1 FROM organisation_conventions oc "
            "WHERE oc.idcc = ccn_reference.idcc)"
        )
    )
