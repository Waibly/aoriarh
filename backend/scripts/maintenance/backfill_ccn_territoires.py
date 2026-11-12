"""Tag the regional agreements already indexed in national CCNs; writes require --apply.

Run from backend: python -m scripts.maintenance.backfill_ccn_territoires
Repeat with --apply after inspecting the preview. Payload only: no re-embedding.

New ingestions set `territoires` themselves (app.rag.ingestion); this covers
chunks indexed before. A KALI text is read from `instrument_title`; an
agreement published alone (BOCC) from its document name. Old KALI snapshots
without `instrument_title` are counted: a resync of their convention fixes them.
"""

import argparse
import asyncio
from collections import Counter, defaultdict

from qdrant_client.models import FieldCondition, Filter, MatchAny
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.ccn import CcnReference
from app.rag.qdrant_store import COLLECTION_NAME, ensure_collection, get_qdrant_client
from app.services.territoire import document_territoires, instrument_territoires

CCN_TYPES = ["convention_collective_nationale", "accord_branche"]


async def _convention_titles() -> dict[str, str]:
    async with async_session_factory() as db:
        rows = await db.execute(select(CcnReference.idcc, CcnReference.titre))
        return dict(rows.all())


def run(apply: bool) -> None:
    conventions = asyncio.run(_convention_titles())
    client = get_qdrant_client()
    ensure_collection(client)  # creates the `territoires` keyword index
    scroll_filter = Filter(must=[FieldCondition(key="source_type", match=MatchAny(any=CCN_TYPES))])
    to_tag: dict[tuple[str, ...], list] = defaultdict(list)
    titles: Counter = Counter()
    stale = 0  # already tagged, but no longer matching
    untitled: Counter = Counter()
    total = 0
    offset = None
    while True:
        points, offset = client.scroll(
            COLLECTION_NAME,
            scroll_filter=scroll_filter,
            limit=1000,
            offset=offset,
            with_payload=["instrument_title", "doc_name", "territoires", "idcc"],
            with_vectors=False,
        )
        for point in points:
            total += 1
            payload = point.payload or {}
            title = payload.get("instrument_title")
            doc_name = payload.get("doc_name") or ""
            if title:
                wanted = instrument_territoires(title, doc_name)
            elif doc_name.startswith(("CCN ", "Accords de branche — ")):
                untitled[payload.get("idcc")] += 1
                continue
            else:  # agreement published alone (BOCC)
                title = doc_name
                wanted = document_territoires(doc_name, conventions.get(payload.get("idcc")))
            current = payload.get("territoires") or []
            if wanted == current:
                continue
            if not wanted:
                stale += 1
            to_tag[tuple(wanted)].append(point.id)
            titles[(tuple(wanted), payload.get("idcc"), title)] += 1
        if offset is None:
            break

    print(f"CCN chunks: {total}, old KALI snapshots without titles: {sum(untitled.values())}")
    print(f"  untitled by IDCC: {dict(untitled.most_common(15))}")
    for (territoires, idcc, title), count in sorted(titles.items()):
        print(f"  {count:4d} IDCC {idcc} {list(territoires) or 'untag'} — {title[:110]}")
    print(f"Chunks to update: {sum(len(v) for v in to_tag.values())} (untag: {stale})")

    if not apply:
        print("Preview only: rerun with --apply to write.")
        return
    for territoires, point_ids in to_tag.items():
        for i in range(0, len(point_ids), 500):
            batch = point_ids[i : i + 500]
            if territoires:
                client.set_payload(
                    COLLECTION_NAME, payload={"territoires": list(territoires)}, points=batch
                )
            else:
                client.delete_payload(COLLECTION_NAME, keys=["territoires"], points=batch)
    print("Applied.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    run(parser.parse_args().apply)
