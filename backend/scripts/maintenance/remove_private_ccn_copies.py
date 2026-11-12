"""Remove the private CCN copies made by the old weekly sync; writes require --apply.

Run from backend: python -m scripts.maintenance.remove_private_ccn_copies
Until 12/11/2026 the weekly sync created, for each organisation, a private copy
of a convention it had installed (storage path « {org}/ccn/{idcc}/… »), on top
of the shared snapshot every organisation reads. A copy is removed only when
the shared snapshot of the same IDCC is indexed with all its vectors.
Documents an organisation uploaded itself are never matched.
"""

import argparse
import asyncio
import re

from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.document import Document
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
from app.services.storage_service import StorageService

_PRIVATE_COPY_PATH = re.compile(r"^[0-9a-f-]{36}/ccn/(\d{4})/[0-9a-f-]{36}\.txt$")


def _vector_count(qdrant, document_id: str) -> int:
    return qdrant.count(
        COLLECTION_NAME,
        count_filter=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
        exact=True,
    ).count


async def run(apply: bool) -> None:
    qdrant = get_qdrant_client()
    storage = StorageService()
    async with async_session_factory() as db:
        copies = [
            doc
            for doc in (
                await db.execute(
                    select(Document).where(
                        Document.organisation_id.isnot(None),
                        Document.source_type == "convention_collective_nationale",
                        Document.name.startswith("CCN "),
                    )
                )
            ).scalars()
            if _PRIVATE_COPY_PATH.match(doc.storage_path or "")
            and doc.storage_path.startswith(f"{doc.organisation_id}/")
        ]
        removed = 0
        for doc in sorted(copies, key=lambda d: (str(d.organisation_id), d.created_at)):
            idcc = _PRIVATE_COPY_PATH.match(doc.storage_path).group(1)
            shared = (
                (
                    await db.execute(
                        select(Document).where(
                            Document.organisation_id.is_(None),
                            Document.source_type == "convention_collective_nationale",
                            Document.name.startswith("CCN "),
                            Document.name.contains(f"(IDCC {idcc})"),
                            Document.indexation_status == "indexed",
                            Document.chunk_count > 0,
                        )
                    )
                )
                .scalars()
                .all()
            )
            ready = [d for d in shared if _vector_count(qdrant, str(d.id)) == d.chunk_count]
            vectors = _vector_count(qdrant, str(doc.id))
            verdict = "remove" if ready else "KEEP (shared snapshot not ready)"
            print(
                f"{verdict:34s} org {doc.organisation_id} IDCC {idcc} "
                f"{doc.created_at:%Y-%m-%d} {vectors} vectors — {doc.name[:60]}"
            )
            if not apply or not ready:
                continue
            qdrant.delete(
                COLLECTION_NAME,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(key="document_id", match=MatchValue(value=str(doc.id)))
                        ]
                    )
                ),
            )
            storage.delete_file(doc.storage_path)
            await db.delete(doc)
            await db.commit()
            removed += 1
        print(f"Private copies: {len(copies)}, removed: {removed}")
        if not apply:
            print("Preview only: rerun with --apply to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args().apply))
