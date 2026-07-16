"""Mesure la couverture du corpus contre une référence EXTERNE.

Pourquoi ce script existe
-------------------------
Le tri des textes JORF repose sur une liste de mots-clés écrite à la main. Une
liste blanche ne peut pas révéler ses propres angles morts : elle ne connaît que
ce qu'on a pensé à y mettre, et rien ne signale ce qu'on a oublié. Auditer le
filtre avec nos propres critères ne prouve donc rien sur le rappel réel.

D'où l'idée : se mesurer contre une référence qu'on n'a PAS écrite. Le Code du
travail numérique (service de la DGT, celui que consultent les RH) publie ses
fiches en open data. Ces fiches citent nommément les lois et décrets sur
lesquels elles s'appuient : c'est, de fait, une liste curée de « ce qu'un outil
RH est censé connaître ».

Le script relève ces citations et regarde combien on en a. Il sort un
pourcentage — pas une impression.

Mesure de référence (2026-07-15, avant rattrapage) : 4/43 lois et 15/161
décrets, soit 9 %.

Limites, à garder en tête pour lire le résultat
-----------------------------------------------
  * Les fiches ne citent qu'une partie du droit : c'est un échantillon, pas
    l'univers. 100 % ici ne voudrait pas dire « corpus complet ».
  * Un texte manquant n'est pas forcément un trou fonctionnel : beaucoup de
    vieilles lois sont entièrement codifiées, et le Code du travail, on l'a en
    entier. Le manque ne fait mal que pour les dispositions NON codifiées
    (expérimentations, mesures transitoires) — précisément la classe qui nous a
    échappé sur la loi Partage de la valeur de 2023.

Usage :
    docker compose -f docker-compose.prod.yml exec backend \
        python scripts/audit_couverture_textes.py
"""
from __future__ import annotations

import asyncio
import collections
import re
import sys

import httpx
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.document import Document

_FICHES_URL = (
    "https://unpkg.com/@socialgouv/fiches-travail-data/data/fiches-travail.json"
)

# Le numéro d'un texte (AAAA-NNN) est la clé de rapprochement : il est présent
# dans le titre Légifrance qu'on stocke tel quel dans Document.name.
_RE_LOI = re.compile(r"(?:loi|LOI)\s+n[°o]\s*(\d{4}-\d+)")
_RE_DECRET = re.compile(r"(?:décret|DÉCRET|Décret)\s+n[°o]\s*(\d{4}-\d+)")
_RE_NUM = re.compile(r"n[°o]\s*(\d{4}-\d+)")


async def _reference() -> tuple[list[str], list[str]]:
    """Lois et décrets cités nommément par les fiches du Code du travail numérique."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.get(_FICHES_URL)
        r.raise_for_status()
        fiches = r.json()

    txt = "\n".join(
        s.get("text") or ""
        for f in fiches
        for s in (f.get("sections") or [])
    )
    return sorted(set(_RE_LOI.findall(txt))), sorted(set(_RE_DECRET.findall(txt)))


async def _corpus() -> set[str]:
    """Numéros des textes JORF présents dans le corpus commun."""
    async with async_session_factory() as db:
        res = await db.execute(
            select(Document.name).where(
                Document.source_type.in_(("loi", "ordonnance", "decret")),
                Document.organisation_id.is_(None),
            )
        )
        return {
            num
            for (name,) in res.all()
            for num in _RE_NUM.findall(name or "")
        }


def _rapport(label: str, attendus: list[str], presents: set[str]) -> list[str]:
    ok = [x for x in attendus if x in presents]
    manquants = [x for x in attendus if x not in presents]
    taux = 100 * len(ok) / len(attendus) if attendus else 0.0
    print(f"{label:<9}: {len(ok):>3}/{len(attendus):<3} = {taux:>5.1f} %")
    return manquants


async def main() -> None:
    try:
        lois, decrets = await _reference()
    except httpx.HTTPError as exc:
        sys.exit(f"Référence inaccessible ({_FICHES_URL}) : {exc}")

    presents = await _corpus()

    print("Couverture du corpus vs textes cités par le Code du travail numérique")
    print("-" * 68)
    manq_l = _rapport("Lois", lois, presents)
    manq_d = _rapport("Décrets", decrets, presents)

    tous = lois + decrets
    ok_total = len(tous) - len(manq_l) - len(manq_d)
    print("-" * 68)
    print(f"{'TOTAL':<9}: {ok_total:>3}/{len(tous):<3} = {100*ok_total/len(tous):>5.1f} %")

    manquants = manq_l + manq_d
    if not manquants:
        print("\nAucun texte de la référence ne manque.")
        return

    print(f"\nManquants par année ({len(manquants)} textes) :")
    par_an = collections.Counter(x.split("-")[0] for x in manquants)
    for annee in sorted(par_an):
        print(f"  {annee} : {par_an[annee]:>3}")

    if manq_l:
        print(f"\nLois manquantes :\n  {', '.join(manq_l)}")


if __name__ == "__main__":
    asyncio.run(main())
