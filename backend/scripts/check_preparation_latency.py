"""Opt-in paid, read-only planner samples. No grading, retries or app data writes.

Run from backend: PYTHONPATH=. .venv/bin/python scripts/check_preparation_latency.py
Original outputs are printed for a separate human review; never gate user rendering.
"""

# ruff: noqa: E501 -- verbatim standalone test situations.
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.rag.agent import _llm
from app.rag.config import EXPAND_MODEL
from app.services.conversation_orchestrator import plan_conversation


async def main():
    profile = {
        "nom": "Entreprise exemple",
        "taille": "1-10",
        "convention_collective": "Syntec (IDCC 1486)",
    }
    fact = {
        "id": "11111111-1111-4111-8111-111111111111",
        "key": "salary",
        "label": "Salaire",
        "entry_type": "fact",
        "status": "active",
        "value_text": "Salaire mensuel brut de 3 200 €",
    }
    doc = {
        "document_id": "22222222-2222-4222-8222-222222222222",
        "extraction_id": "33333333-3333-4333-8333-333333333333",
        "source_name": "Contrat exemple",
        "text": "CDI signé le 15 mars 2018. Salaire mensuel brut : 3 200 euros. Un treizième mois est versé en décembre.",
        "transmitted_scope": "full_extracted_text",
    }
    cases = [
        ("simple", "Un employeur peut-il refuser une demande de télétravail ?", [], []),
        ("date", "Entretiens professionnels : que vérifier avant le 1er octobre 2026 ?", [], []),
        (
            "multi",
            "Entreprise de 42 salariés. Salarié en CDI depuis le 15 mars 2018, salaire brut de 3 200 €, 13e mois et prime de 8 000 € en juin 2026 pour la mission du 1er avril au 30 juin. Nature de la prime et CCN inconnues. Licenciement économique envisagé. Quelles pièces réunir, comment traiter les primes, et prépare un mail à la paie. Aucun calcul.",
            [],
            [],
        ),
        (
            "correction",
            "Correction : mon salaire mensuel brut est de 3 450 €, et non 3 200 €. Mets le dossier à jour, sans calcul.",
            [fact],
            [],
        ),
        (
            "contradiction",
            "Le profil indique Syntec mais cette convention ne s'applique pas au salarié. La CCN applicable reste inconnue. Quelles informations réunir pour déterminer son préavis ?",
            [],
            [],
        ),
        (
            "piece",
            "À partir du contrat joint, indique la date d'entrée et les éléments de rémunération.",
            [],
            [doc],
        ),
        (
            "calcul",
            "Salarié en CDI depuis le 15 mars 2018. Salaire fixe mensuel brut 3 200 €, aucun bonus, rupture envisagée le 30 septembre 2026. Calcule l'indemnité légale de licenciement, en recherchant d'abord la règle applicable. CCN à confirmer.",
            [],
            [],
        ),
    ]
    agent = SimpleNamespace(
        llm=_llm, _org_id=None, _user_id=None, _conversation_id=None, _is_replay=True
    )
    # This standalone experiment reports usage locally, outside application billing.
    with patch("app.services.cost_tracker.cost_tracker.log_bg"):
        for name, query, entries, docs in cases:
            result = await plan_conversation(
                agent,
                query=query,
                history=[],
                active_documents=[
                    {
                        "document_id": d["document_id"],
                        "extraction_id": d["extraction_id"],
                        "name": d["source_name"],
                    }
                    for d in docs
                ],
                documents=docs,
                tool_results=[],
                continuation=False,
                model=EXPAND_MODEL,
                org_context=profile,
                org_idcc_list=["1486"],
                case_file_context={
                    "version": 1,
                    "status": "active",
                    "entries": entries,
                    "tasks": [],
                    "documents": [],
                },
            )
            print(
                json.dumps(
                    {
                        "case": name,
                        "metrics": result.trace.search_plan_usage,
                        "perf_ms": result.trace.perf_ms,
                        "error": result.trace.error,
                        "validation": result.trace.search_plan_validation,
                        "raw": result.raw,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    await _llm.close()


if __name__ == "__main__":
    asyncio.run(main())
