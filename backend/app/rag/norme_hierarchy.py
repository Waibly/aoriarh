from enum import IntEnum


class NormeNiveau(IntEnum):
    """Hiérarchie des normes du droit social français (1 = plus fort).

    Conforme au cahier des charges section 5.3.
    """

    CONSTITUTION = 1
    NORMES_INTERNATIONALES = 2
    LOIS_ORDONNANCES = 3
    JURISPRUDENCE = 4
    REGLEMENTAIRE = 5
    CONVENTIONS_COLLECTIVES = 6
    USAGES_ENGAGEMENTS = 7
    REGLEMENT_INTERIEUR = 8
    CONTRAT_TRAVAIL = 9
    DIVERS = 10


NORME_POIDS: dict[int, float] = {
    1: 1.0,
    2: 0.95,
    3: 0.90,
    4: 0.85,
    5: 0.80,
    6: 0.75,
    7: 0.65,
    8: 0.55,
    9: 0.50,
    10: 0.40,
}


# Types de documents nécessitant le chunker jurisprudence
JURISPRUDENCE_SOURCE_TYPES = frozenset({
    "arret_cour_cassation",
    "arret_conseil_etat",
    "decision_conseil_constitutionnel",
})


DOCUMENT_TYPE_HIERARCHY: dict[str, dict] = {
    # Niveau 1 — Constitution
    "constitution": {"niveau": 1, "poids": 1.0},
    "bloc_constitutionnalite": {"niveau": 1, "poids": 1.0},
    # Niveau 2 — Normes internationales
    "traite_international": {"niveau": 2, "poids": 0.95},
    "convention_oit": {"niveau": 2, "poids": 0.95},
    "directive_europeenne": {"niveau": 2, "poids": 0.95},
    "reglement_europeen": {"niveau": 2, "poids": 0.95},
    "charte_droits_fondamentaux": {"niveau": 2, "poids": 0.95},
    # Niveau 3 — Lois & Ordonnances
    "code_travail": {"niveau": 3, "poids": 0.90},
    "loi": {"niveau": 3, "poids": 0.90},
    "ordonnance": {"niveau": 3, "poids": 0.90},
    "code_securite_sociale": {"niveau": 3, "poids": 0.90},
    "code_penal": {"niveau": 3, "poids": 0.90},
    "code_civil": {"niveau": 3, "poids": 0.90},
    # Niveau 4 — Jurisprudence
    "arret_cour_cassation": {"niveau": 4, "poids": 0.85},
    "arret_conseil_etat": {"niveau": 4, "poids": 0.85},
    "decision_conseil_constitutionnel": {"niveau": 4, "poids": 0.85},
    # Niveau 5 — Réglementaire
    "decret": {"niveau": 5, "poids": 0.80},
    "arrete": {"niveau": 5, "poids": 0.80},
    "circulaire": {"niveau": 5, "poids": 0.80},
    "code_travail_reglementaire": {"niveau": 5, "poids": 0.80},
    # Niveau 6 — Conventions collectives
    "accord_national_interprofessionnel": {"niveau": 6, "poids": 0.75},
    "accord_branche": {"niveau": 6, "poids": 0.70},
    "convention_collective_nationale": {"niveau": 6, "poids": 0.70},
    "accord_entreprise": {"niveau": 6, "poids": 0.65},
    "accord_performance_collective": {"niveau": 6, "poids": 0.60},
    # Niveau 7 — Usages & Engagements
    "usage_entreprise": {"niveau": 7, "poids": 0.65},
    "engagement_unilateral": {"niveau": 7, "poids": 0.65},
    # Niveau 8 — Règlement intérieur
    "reglement_interieur": {"niveau": 8, "poids": 0.55},
    # Niveau 9 — Contrat de travail
    "contrat_travail": {"niveau": 9, "poids": 0.50},
    # Niveau 10 — Divers
    "divers": {"niveau": 10, "poids": 0.40},
}

SOURCE_TYPES = list(DOCUMENT_TYPE_HIERARCHY.keys())
