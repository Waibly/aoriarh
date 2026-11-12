"""Replace guessed ``content_date`` values in Qdrant with official dates.

Until Nov. 2026, chunks of Codes, conventions and JORF acts received the most
recent French date written in their text (often a cited law or a future
deadline). Ingestion now uses the article's entry-into-force date when known,
else the document's official date (publication, entry into force, update,
signature), else nothing. This script applies the same rule to chunks already
indexed: payload update only, no embedding, no document change.

Default: dry run (counts only). ``--apply`` writes the payloads.
"""

import argparse
import asyncio
from collections import Counter, defaultdict

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.models.document import Document
from app.rag.ingestion import ARTICLE_AWARE_SOURCE_TYPES, document_content_date
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client


def _plan_document(qdrant, doc: Document) -> tuple[dict[str | None, list], Counter]:
    """Group the document's points by the content_date they should carry."""
    official = document_content_date(doc)
    changes: dict[str | None, list] = defaultdict(list)
    stats: Counter = Counter()
    offset = None
    while True:
        points, offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=str(doc.id)))]
            ),
            limit=500,
            offset=offset,
            with_payload=["content_date", "effective_from"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            wanted = payload.get("effective_from") or official
            current = payload.get("content_date")
            stats["points"] += 1
            if current == wanted:
                continue
            changes[wanted].append(point.id)
            stats["removed" if wanted is None else "changed"] += 1
        if offset is None:
            break
    return changes, stats


async def main(apply: bool) -> None:
    qdrant = get_qdrant_client()
    async with async_session_factory() as db:
        docs = (
            (
                await db.execute(
                    select(Document).where(
                        Document.source_type.in_(sorted(ARTICLE_AWARE_SOURCE_TYPES | {"boss"})),
                        Document.indexation_status == "indexed",
                    )
                )
            )
            .scalars()
            .all()
        )
    total: Counter = Counter()
    by_type: Counter = Counter()
    for doc in docs:
        changes, stats = _plan_document(qdrant, doc)
        total.update(stats)
        if changes:
            total["documents"] += 1
            by_type[doc.source_type] += sum(len(ids) for ids in changes.values())
        if not apply:
            continue
        for wanted, ids in changes.items():
            for i in range(0, len(ids), 500):
                batch = ids[i : i + 500]
                if wanted is None:
                    qdrant.delete_payload(
                        collection_name=COLLECTION_NAME, keys=["content_date"], points=batch
                    )
                else:
                    qdrant.set_payload(
                        collection_name=COLLECTION_NAME,
                        payload={"content_date": wanted},
                        points=batch,
                    )
    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(docs)} documents scanned")
    print(
        f"points={total['points']} changed={total['changed']} "
        f"removed={total['removed']} documents_touched={total['documents']}"
    )
    for source_type, count in by_type.most_common():
        print(f"  {source_type}: {count}")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the payloads")
    asyncio.run(main(parser.parse_args().apply))
