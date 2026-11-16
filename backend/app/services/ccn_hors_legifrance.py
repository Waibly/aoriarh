"""Conventions collectives dont le texte n'est pas publié sur Légifrance.

Certaines conventions locales (BTP de La Réunion : IDCC 0627, 0771, 2389) sont
étendues et ont un IDCC, mais KALI ne contient aucun de leurs textes. Seuls
leurs accords récents paraissent au BOCC. Leur texte de base est repris d'une
publication sérieuse mais non officielle (la caisse de congés payés du BTP de
La Réunion, organisme paritaire de la branche) et rangé dans
``app/reference/ccn_hors_legifrance/<idcc>.json``.

Ces fichiers produisent les mêmes articles que KALI : l'installation, la
synchronisation hebdomadaire (mise à jour au déploiement d'un fichier modifié)
et la recherche les traitent comme n'importe quelle convention.
"""

import json
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "reference" / "ccn_hors_legifrance"


@cache
def _registry() -> dict[str, dict]:
    conventions: dict[str, dict] = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        conventions[data["idcc"]] = data
    return conventions


def hors_legifrance_idcc() -> set[str]:
    return set(_registry())


def is_hors_legifrance(idcc: str | None) -> bool:
    return bool(idcc) and idcc in _registry()


def reference_rows() -> list[dict]:
    """Lignes du référentiel des conventions (ccn_reference) à garantir."""
    return [
        {
            "idcc": data["idcc"],
            "titre": data["titre"],
            "titre_court": data["titre_court"],
            "etat": data["etat"],
        }
        for data in _registry().values()
    ]


def hors_legifrance_articles(idcc: str) -> tuple[list[dict], str | None]:
    """Articles de la convention au format produit par la lecture KALI.

    Retourne (articles, date du texte le plus récent)."""
    data = _registry()[idcc]
    articles: list[dict] = []
    most_recent: str | None = None
    for text in data["texts"]:
        date = text.get("date") or ""
        if date and (most_recent is None or date > most_recent):
            most_recent = date
        title = text["title"]
        if text.get("source"):
            title = f"{title} — source : {text['source']}"
        for article in text["articles"]:
            articles.append(
                {
                    "num": article["num"],
                    "content": article["content"],
                    "section": article.get("section", ""),
                    "article_id": f"{text['id']}/{article['num']}",
                    "article_title": article.get("article_title", ""),
                    "etat": "VIGUEUR",
                    "date_debut": date,
                    "date_fin": "",
                    "category": text["category"],
                    "instrument_id": text["id"],
                    "instrument_title": title,
                    "instrument_status": text.get("status", "VIGUEUR_ETEN"),
                }
            )
    return articles, most_recent
