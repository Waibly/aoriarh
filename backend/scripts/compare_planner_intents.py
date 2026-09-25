"""Explicit standalone paid comparison; original outputs, no grading or repair.

From backend: PYTHONPATH=. .venv/bin/python scripts/compare_planner_intents.py capture DIR
Capture before and after code changes with distinct directories; run DIR to execute
the frozen requests. No application data, billing writes, or automatic retries.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from openai import AsyncOpenAI

from app.core.config import settings
from app.rag.config import EXPAND_MODEL
from app.services.conversation_orchestrator import plan_conversation

CASES = [
    ("simple", "Un employeur peut-il refuser le télétravail ?"),
    ("checklist", "Entretiens professionnels : que vérifier avant le 1er octobre 2026 ?"),
    (
        "pieces",
        "Quels documents réunir pour vérifier mon indemnité de licenciement ? Aucun calcul.",
    ),
    ("mail", "Rédige uniquement un mail à la paie pour demander mes bulletins manquants."),
    ("comparaison", "Compare rupture conventionnelle et licenciement économique côté salarié."),
    (
        "multi",
        "CDI depuis le 15 mars 2018, salaire brut 3 200 €, 13e mois et prime de 8 000 € "
        "versée en juin 2026 pour la mission du 1er avril au 30 juin. "
        "CCN et nature de la prime inconnues. Licenciement économique : quelles pièces réunir, "
        "comment traiter les primes et prépare un mail à la paie. Aucun calcul.",
    ),
    (
        "correction",
        "Corrige seulement le salaire du mail précédent : 3 450 € brut mensuel, "
        "pas 3 200 €. Garde le reste.",
    ),
    (
        "ccn",
        "Le profil indique Syntec mais elle ne s'applique pas à mon cas. CCN inconnue. "
        "Quelles informations faut-il pour déterminer mon préavis ?",
    ),
    (
        "contradiction",
        "Mon employeur dit que ma prime est annuelle, mon contrat dit qu'elle rémunère "
        "la mission avril-juin. Quels éléments vérifier ?",
    ),
    (
        "date",
        "La lettre a été déposée sur Maileva le 30 juin 2026, reçue le 2 juillet. "
        "Quelle date retenir pour la notification ?",
    ),
    (
        "calcul",
        "CDI depuis le 15 mars 2018, salaire fixe mensuel brut 3 200 €, "
        "rupture au 30 septembre 2026. Calcule mon indemnité légale après recherche de la règle. "
        "CCN à confirmer.",
    ),
    (
        "source",
        "Retrouve le dernier contrat que j'ai déposé, "
        "puis indique les dates et rémunérations prévues.",
    ),
]


async def capture(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, query in CASES:
        call = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}", refusal=None))],
                usage=None,
            )
        )
        llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=call)))
        llm.with_options = lambda **kwargs: llm
        await plan_conversation(
            SimpleNamespace(llm=llm),
            query=query,
            history=[
                {
                    "role": "assistant",
                    "content": "Bonjour, merci de vérifier le salaire mensuel brut de 3 200 € "
                    "et de transmettre le détail des primes et du treizième mois. Cordialement.",
                }
            ]
            if name == "correction"
            else [],
            active_documents=[],
            documents=[],
            tool_results=[],
            continuation=False,
            model=EXPAND_MODEL,
            org_context={"taille": "20-49", "convention_collective": "Syntec (IDCC 1486)"},
            org_idcc_list=["1486"],
            case_file_context={"version": 1, "entries": [], "tasks": [], "documents": []},
        )
        (directory / f"{name}.input.json").write_text(
            json.dumps(call.call_args.kwargs, ensure_ascii=False)
        )


async def run(directory, repetitions):
    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=300)
    semaphore = asyncio.Semaphore(2)

    async def one(path, repeat):
        target = directory / f"{path.name.removesuffix('.input.json')}.{repeat}.output.json"
        if target.exists():
            return
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await client.chat.completions.create(**json.loads(path.read_text()))
                result = {"response": response.model_dump(), "error": None}
            except Exception as exc:
                result = {"response": None, "error": type(exc).__name__}
            result["seconds"] = time.perf_counter() - started
            with target.open("x") as output:
                json.dump(result, output, ensure_ascii=False)
            print(target.name, round(result["seconds"], 2), result["error"], flush=True)

    try:
        await asyncio.gather(
            *(
                one(path, repeat)
                for repeat in range(repetitions)
                for path in sorted(directory.glob("*.input.json"))
            )
        )
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "run"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(
        capture(args.directory)
        if args.action == "capture"
        else run(args.directory, args.repetitions)
    )
