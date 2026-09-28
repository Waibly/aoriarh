"""Read official JORF metadata for existing documents; writes require --apply.

Run from backend: python -m scripts.maintenance.hydrate_jorf_dates --limit 100
Repeat with --apply after inspecting the preview. No re-embedding or text changes.
Use --after-id to advance beyond documents with unknown official publication dates.
"""

import argparse
import asyncio
import json
import uuid
from datetime import date

import httpx
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.document import Document
from app.services.jorf_service import JorfService


async def hydrate_year(*, year, natures, max_pages=200, apply=False):
    """Read publication metadata in official search pages, matching exact CIDs.

    This avoids one consultation per historical decree. No date is inferred
    from the document title or the search window. Transactions are per page.
    """
    service = JorfService()
    async with async_session_factory() as db, httpx.AsyncClient(timeout=30) as client:
        documents = (
            await db.scalars(
                select(Document).where(
                    Document.organisation_id.is_(None),
                    Document.storage_path.startswith("common/jorf/", autoescape=True),
                    Document.publication_date.is_(None),
                    Document.numero_pourvoi.isnot(None),
                )
            )
        ).all()
        by_cid = {doc.numero_pourvoi: doc for doc in documents}
        fetched = matched = 0
        complete = False
        for page in range(1, max_pages + 1):
            payload = service._build_search_payload(page, date(year, 1, 1), date(year, 12, 31))
            payload["recherche"]["filtres"][0]["valeurs"] = natures
            data = await service._api_post(client, "/search", payload)
            if not data:
                raise RuntimeError("jorf_search_metadata_unavailable")
            rows = data.get("results", [])
            fetched += len(rows)
            updates = 0
            for raw in rows:
                cid, _, _ = service._parse_search_result(raw)
                publication = service._source_date(raw, ("datePublication",))
                doc = by_cid.get(cid)
                if doc is None or publication is None:
                    continue
                if apply:
                    doc.publication_date = publication
                    doc.source_url = f"https://www.legifrance.gouv.fr/jorf/id/{cid}"
                by_cid.pop(cid)
                updates += 1
            if apply:
                await db.commit()
            matched += updates
            print(
                json.dumps(
                    {
                        "year": year,
                        "page": page,
                        "fetched": fetched,
                        "matched": matched,
                        "apply": apply,
                    }
                ),
                flush=True,
            )
            if fetched >= data.get("totalResultNumber", 0):
                complete = True
                break
            if not rows:
                raise RuntimeError("jorf_search_incomplete_pagination")
        print(json.dumps({"year": year, "complete": complete, "matched": matched}), flush=True)
        if not complete:
            raise RuntimeError("jorf_search_page_limit_reached")


async def hydrate(*, limit, after_id=None, apply=False):
    service = JorfService()
    query = (
        select(Document)
        .where(
            Document.organisation_id.is_(None),
            Document.storage_path.startswith("common/jorf/", autoescape=True),
            Document.publication_date.is_(None),
            Document.numero_pourvoi.isnot(None),
        )
        .order_by(Document.id)
        .limit(limit)
    )
    if after_id:
        query = query.where(Document.id > after_id)
    async with async_session_factory() as db, httpx.AsyncClient(timeout=30) as client:
        documents = (await db.scalars(query)).all()
        for doc in documents:
            cid = doc.numero_pourvoi
            raw = await service._api_post(client, "/consult/jorf", {"textCid": cid})
            if not raw:
                raise RuntimeError("jorf_metadata_unavailable")
            publication = service._source_date(raw, ("dateParution", "datePublication"))
            effective = service._source_date(raw, ("dateEntreeVigueur",))
            print(
                json.dumps(
                    {
                        "document_id": str(doc.id),
                        "cid": cid,
                        "publication_date": str(publication) if publication else None,
                        "effective_date": str(effective) if effective else None,
                        "apply": apply,
                    },
                    ensure_ascii=False,
                )
            )
            if apply:
                doc.publication_date = publication
                doc.effective_date = effective
                doc.source_url = f"https://www.legifrance.gouv.fr/jorf/id/{cid}"
        if apply:
            await db.commit()
        print(
            json.dumps(
                {
                    "processed": len(documents),
                    "next_after_id": str(documents[-1].id) if documents else None,
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--after-id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--publication-year", type=int)
    parser.add_argument(
        "--nature", action="append", choices=["DECRET", "LOI", "ORDONNANCE", "ARRETE"]
    )
    parser.add_argument("--max-pages", type=int, default=200)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.publication_year is not None:
        if not 1900 <= args.publication_year <= date.today().year or not 1 <= args.max_pages <= 200:
            parser.error("Invalid publication year or page budget")
        asyncio.run(
            hydrate_year(
                year=args.publication_year,
                natures=args.nature or ["DECRET", "LOI", "ORDONNANCE"],
                max_pages=args.max_pages,
                apply=args.apply,
            )
        )
    else:
        asyncio.run(hydrate(limit=args.limit, after_id=args.after_id, apply=args.apply))
