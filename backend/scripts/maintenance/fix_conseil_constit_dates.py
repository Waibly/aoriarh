"""Give a date to Conseil constitutionnel decisions stored without one.

Until Nov. 2026 the date was read from the title only, and « 1er octobre 2026 »
was not recognised: those decisions have no date in their name, header or
filters. This script reads the official date (``dateTexte``) from Légifrance,
fixes the date and the display name, then reindexes the document so every
passage header carries the date. Text and identifiers are unchanged.

Default: dry run. ``--apply`` writes and enqueues the reindexing.
"""

import argparse
import asyncio

import httpx
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.models.document import Document
from app.rag.tasks import enqueue_ingestion
from app.services.conseil_constit_service import ConseilConstitService


async def main(apply: bool) -> None:
    service = ConseilConstitService()
    async with async_session_factory() as db:
        docs = (
            (
                await db.execute(
                    select(Document).where(
                        Document.source_type == "decision_conseil_constitutionnel",
                        Document.organisation_id.is_(None),
                        Document.date_decision.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        print(f"{len(docs)} decision(s) without a date")
        fixed = []
        async with httpx.AsyncClient(timeout=60) as client:
            for doc in docs:
                data = await service._api_post(
                    client, "/consult/juri", {"textId": doc.numero_pourvoi}
                )
                text_obj = (data or {}).get("text") or {}
                title = text_obj.get("titre") or ""
                official = service._official_date(text_obj) or service._parse_date_from_title(title)
                if official is None:
                    print(f"  ? {doc.name} ({doc.numero_pourvoi}): no official date")
                    continue
                name = service.display_name(title, doc.publication or "", official)
                print(f"  {doc.name} -> {name}")
                if apply:
                    doc.date_decision = official
                    doc.name = name
                    doc.indexation_status = "pending"
                    doc.indexation_error = None
                    fixed.append(doc)
        if apply and fixed:
            await db.commit()
            for doc in fixed:
                await enqueue_ingestion(str(doc.id), expected_source=doc.storage_path)
            print(f"APPLIED: {len(fixed)} decision(s) dated and queued for reindexing")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write and reindex")
    asyncio.run(main(parser.parse_args().apply))
