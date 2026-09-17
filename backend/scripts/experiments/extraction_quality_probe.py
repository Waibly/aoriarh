"""Offline lot 1B comparison; --run explicitly enables 16 paid calls, no retries."""

import argparse
import asyncio
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def fixtures():
    from scripts.experiments.document_continuity_probe import fixtures as previous_fixtures

    return [
        dict(
            id="travail_effectif",
            name="Code du travail — L3121-1",
            kind="code_travail",
            text="### Article L3121-1\nLa durée du travail effectif est le temps pendant lequel "
            "le salarié est à la disposition de l'employeur et se conforme à ses directives "
            "sans pouvoir vaquer librement à des occupations personnelles.",
            question="En droit du travail privé français, quelles sont les conditions du travail "
            "effectif selon l'article fourni ?",
        ),
        dict(
            id="essai_cadre",
            name="Code du travail — L1221-19",
            kind="code_travail",
            text="### Article L1221-19\nLe contrat de travail à durée indéterminée peut comporter "
            "une période d'essai dont la durée maximale est :\n"
            "1° Pour les ouvriers et les employés, "
            "de deux mois ;\n2° Pour les agents de maîtrise et les techniciens, de trois mois ;\n"
            "3° Pour les cadres, de quatre mois.",
            question="Cadre recruté en CDI dans le privé, quelle durée maximale légale pour la "
            "période d'essai initiale, hors renouvellement ? Je demande uniquement la limite "
            "légale de l'article fourni.",
        ),
        dict(
            id="heures_supplementaires",
            name="Code du travail — L3121-36",
            kind="code_travail",
            text="### Article L3121-36\nA défaut d'accord, les heures supplémentaires accomplies "
            "au-delà de la durée légale hebdomadaire fixée à l'article L. 3121-27 ou de la durée "
            "considérée comme équivalente donnent lieu à une majoration de salaire de 25 % pour "
            "chacune des huit premières heures supplémentaires. Les heures suivantes donnent "
            "lieu à une majoration de 50 %.",
            question="Exercice de paie en droit privé : dix heures supplémentaires dans la même "
            "semaine, taux horaire brut de base 20 euros, absence d'accord supposée. Selon "
            "l'article fourni, calcule leur rémunération totale et le seul supplément "
            "de majoration.",
        ),
        dict(
            id="contradiction",
            name=previous_fixtures()[0]["docs"][0].name,
            kind="divers",
            text=previous_fixtures()[0]["docs"][0].text,
            question=previous_fixtures()[0]["question"],
        ),
    ]


async def build_pairs():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.models  # noqa: F401 — complete metadata registry
    from app.models.base import Base
    from app.models.document import Document
    from app.models.membership import Membership
    from app.models.organisation import Organisation
    from app.models.user import User
    from app.rag.agent import RAGAgent, _generation_system_prompt
    from app.rag.article_chunker import ArticleChunker
    from app.rag.chunker import LegalChunker
    from app.rag.search import SearchResult
    from app.rag.text_cleaner import clean_text
    from app.rag.text_extractor import TextExtractor
    from app.services.document_extraction_service import DocumentExtractionService, SourceSnapshot

    class MemoryStorage:
        def __init__(self):
            self.objects = {}

        def put_file_bytes(self, path, data, content_type):
            self.objects[path] = data

        def get_file_bytes_bounded(self, path, budget):
            data = self.objects[path]
            if len(data) > budget:
                raise ValueError("read_budget_exceeded")
            return data

    engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pairs = []
    agent = RAGAgent.__new__(RAGAgent)
    system, max_output = _generation_system_prompt()
    try:
        async with factory() as db:
            org = Organisation(id=uuid.uuid4(), name="Synthetic quality fixture")
            user = User(id=uuid.uuid4(), email="quality@example.test", full_name="Synthetic")
            db.add_all([org, user])
            await db.flush()
            db.add(Membership(user_id=user.id, organisation_id=org.id, role_in_org="user"))
            await db.commit()
            service = DocumentExtractionService(db, MemoryStorage())
            for case in fixtures():
                data = case["text"].encode()
                doc = Document(
                    id=uuid.uuid4(),
                    organisation_id=org.id,
                    name=case["name"],
                    source_type=case["kind"],
                    file_format="txt",
                    storage_path=f"{org.id}/{case['id']}.txt",
                    file_hash=hashlib.sha256(data).hexdigest(),
                )
                db.add(doc)
                await db.commit()
                a = TextExtractor().extract(data, "txt")
                await service.extract(SourceSnapshot.from_document(doc), data, TextExtractor())
                manifest = await service.status(doc.id, org.id, user.id)
                b = (await service.read(doc.id, org.id, user.id, manifest["extraction_id"], 24000))[
                    "text"
                ]
                assert a == b, "raw extraction integrity regression"
                chunker = ArticleChunker() if case["kind"] == "code_travail" else LegalChunker()
                contexts = []
                for raw in (a, b):
                    chunks = chunker.chunk(clean_text(raw))
                    assert chunks
                    results = [
                        SearchResult(
                            text=value,
                            doc_name=case["name"],
                            document_id=case["id"],
                            source_type=case["kind"],
                            norme_niveau=1 if case["kind"] == "code_travail" else 9,
                            norme_poids=1.0,
                            chunk_index=i,
                            score=1.0,
                        )
                        for i, value in enumerate(chunks)
                    ]
                    contexts.append(agent._build_context(results))
                assert contexts[0] == contexts[1], "chunk/context integrity regression"
                for repeat in (1, 2):
                    for variant, context in zip(("A", "B"), contexts):
                        messages = [
                            dict(role="system", content=system),
                            dict(
                                role="user",
                                content=agent._build_user_message(case["question"], context),
                            ),
                        ]
                        pairs.append(
                            dict(
                                case=case["id"],
                                variant=variant,
                                repeat=repeat,
                                messages=messages,
                                max_completion_tokens=max_output,
                                prompt_sha256=hashlib.sha256(
                                    json.dumps(messages, ensure_ascii=False).encode()
                                ).hexdigest(),
                                raw_text_sha256=hashlib.sha256(a.encode()).hexdigest(),
                            )
                        )
    finally:
        await engine.dispose()
    return pairs


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from openai import AsyncOpenAI

    from app.core.config import settings
    from app.services.cost_tracker import PRICING, compute_cost

    pairs = await build_pairs()
    if ("openai", settings.llm_model) not in PRICING:
        raise RuntimeError("unknown price; refusing paid calls")
    bound = sum(
        float(
            compute_cost(
                "openai",
                settings.llm_model,
                sum(len(m["content"].encode()) for m in p["messages"]) + 1024,
                p["max_completion_tokens"],
            )
        )
        for p in pairs
    )
    if bound > 5:
        raise RuntimeError("local conservative bound exceeds 5 USD")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "prompts.json").write_text(
        json.dumps(
            dict(
                model=settings.llm_model,
                reasoning=settings.llm_reasoning_effort,
                local_upper_estimate_usd=bound,
                pairs=pairs,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    print(
        f"{len(pairs)} calls, local bound ${bound:.4f}; raw texts and A/B prompts identical",
        flush=True,
    )
    if not args.run:
        return
    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=120)
    semaphore = asyncio.Semaphore(2)

    async def run(pair):
        async with semaphore:
            started = time.perf_counter()
            record = {key: pair[key] for key in ("case", "variant", "repeat", "prompt_sha256")}
            try:
                response = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=pair["messages"],
                    max_completion_tokens=pair["max_completion_tokens"],
                    reasoning_effort=settings.llm_reasoning_effort,
                )
                record["response"] = response.model_dump(mode="json")
                record["raw_text"] = response.choices[0].message.content
                if response.usage:
                    record["estimated_usd"] = float(
                        compute_cost(
                            "openai",
                            settings.llm_model,
                            response.usage.prompt_tokens,
                            response.usage.completion_tokens,
                        )
                    )
            except Exception as exc:
                record["technical_error"] = type(exc).__name__
            record["seconds"] = time.perf_counter() - started
            name = f"{pair['case']}-{pair['variant']}-{pair['repeat']}"
            (args.output / f"{name}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2)
            )
            print(
                f"{name}: {record['seconds']:.1f}s ${record.get('estimated_usd', 0):.4f} "
                f"{record.get('technical_error', '')}",
                flush=True,
            )
            return record

    order = []
    for i in range(0, len(pairs), 2):
        order.extend(pairs[i : i + 2] if (i // 2) % 2 == 0 else reversed(pairs[i : i + 2]))
    try:
        records = await asyncio.gather(*(run(pair) for pair in order))
    finally:
        await client.close()
    (args.output / "results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
