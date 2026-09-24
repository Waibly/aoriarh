"""Explicit, paid before/after experiment on frozen local contexts; no grading.

snapshot DIR captures the current prompt without paid calls. compare DIR runs each
saved prompt and the current prompt once with identical inputs/model/settings.
Outputs stay outside application conversations. No automatic retries or repair.
"""

import argparse
import asyncio
import json
import time
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from openai import AsyncOpenAI
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.rag.agent import RAGAgent
from app.rag.search import SearchResult

CASES = {
    "checklist": "3ed265bb-5105-4d04-9da3-d2ff15f13569",
    "multi": "bf328d1d-59c7-48b7-8d00-f5b213717929",
    "correction": "efe29f65-9aa1-424f-9026-8d4b282966d2",
}


async def capture(inputs):
    async def empty():
        if False:
            yield

    agent = RAGAgent.__new__(RAGAgent)
    call = AsyncMock(return_value=empty())
    agent.llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=call)))
    kwargs = {**inputs, "results": [SearchResult(**r) for r in inputs["results"]]}
    async for _ in agent.stream_generate(**kwargs):
        pass
    return call.call_args.kwargs


async def snapshot(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    async with engine.connect() as db:
        for name, identifier in CASES.items():
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT m.*, u.profil_metier FROM messages m "
                            "JOIN conversations c ON c.id=m.conversation_id "
                            "JOIN users u ON u.id=c.user_id WHERE m.id=:id AND u.email=:email"
                        ),
                        {"id": identifier, "email": "hello@aoriarh.fr"},
                    )
                )
                .mappings()
                .one()
            )
            trace = row["rag_trace"]
            previous = (
                (
                    await db.execute(
                        text(
                            "SELECT role,content FROM messages WHERE conversation_id=:id "
                            "AND created_at<:date ORDER BY created_at"
                        ),
                        {"id": row["conversation_id"], "date": row["created_at"]},
                    )
                )
                .mappings()
                .all()
            )
            query = previous[-1]["content"]
            history = [dict(m) for m in previous[:-1]][-6:]
            results = []
            allowed = {f.name for f in fields(SearchResult)}
            for source in row["sources"] or []:
                for index, passage in enumerate(
                    source.get("context_passages") or [{"text": source["full_text"]}]
                ):
                    value = {k: v for k, v in source.items() if k in allowed}
                    value.update({k: v for k, v in passage.items() if k in allowed})
                    value.update(
                        doc_name=source["document_name"],
                        text=passage["text"],
                        chunk_index=index,
                        norme_poids=1.0,
                        score=1.0,
                    )
                    results.append(value)
            inputs = dict(
                query=query,
                results=results,
                history=history,
                org_context={
                    "nom": "Waibly",
                    "taille": "1-10",
                    "convention_collective": "Syntec (IDCC 1486)",
                },
                case_context=(trace.get("case_file_observation") or {}).get("execution"),
                condensed_query=trace.get("query_condensed"),
                answer_format=(trace.get("search_plan") or {}).get("answer_format"),
                model_override="gpt-5.6-terra",
            )
            data = {"inputs": inputs, "before": await capture(inputs)}
            (directory / f"{name}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
    await engine.dispose()


async def compare(directory, resume=False, after_label="after", only_after=False):
    for index, name in enumerate(CASES):
        data = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        variants = {"before": data["before"], after_label: await capture(data["inputs"])}
        order = ["before", after_label] if index % 2 == 0 else [after_label, "before"]
        for variant in [after_label] if only_after else order:
            output = directory / f"{name}-{variant}.json"
            if output.exists():
                if resume:
                    print(f"Already recorded: {name}/{variant}", flush=True)
                    continue
                raise RuntimeError(f"Refusing to overwrite {output}")
            started = time.perf_counter()
            first = None
            answer = ""
            usage = None
            error = None
            try:
                async with AsyncOpenAI(
                    api_key=settings.openai_api_key, max_retries=0, timeout=300
                ) as client:
                    stream = await client.chat.completions.create(**variants[variant])
                    async for chunk in stream:
                        if chunk.usage:
                            usage = chunk.usage.model_dump()
                        if chunk.choices and chunk.choices[0].delta.content:
                            if first is None:
                                first = time.perf_counter() - started
                            answer += chunk.choices[0].delta.content
            except Exception as exc:
                error = type(exc).__name__
            metrics = {
                "case": name,
                "variant": variant,
                "first_s": first,
                "total_s": time.perf_counter() - started,
                "chars": len(answer),
                "usage": usage,
                "error": error,
            }
            output.write_text(
                json.dumps(
                    {**metrics, "answer": answer, "request": variants[variant]}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            print(json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "compare"])
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--resume", action="store_true", help="Skip recorded calls, including errors"
    )
    parser.add_argument("--after-label", default="after", choices=["after", "final"])
    parser.add_argument("--only-after", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        snapshot(args.directory)
        if args.mode == "snapshot"
        else compare(args.directory, args.resume, args.after_label, args.only_after)
    )
