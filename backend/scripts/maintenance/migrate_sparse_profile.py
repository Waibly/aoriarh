"""Report by default; --apply builds a separate French index with a fixed budget.

Copy into a new collection on Qdrant 1.13. Freeze writers during the final copy
and full verify. Then activate the collection and French profile together.
No collection deletion, dense re-embedding or automatic switch.

Before applying: check space for the source, destination and both WALs. Freeze
all writers (worker ingestion AND API document replacements/deletions) for the
final copy and verify. Use --resume with next_offset for each bounded passage.
Do not cut over if verify reports a divergence; a live backfill alone is not a
consistent snapshot. Activate QDRANT_COLLECTION_NAME and RAG_LEXICAL_PROFILE
together in backend and worker only after verification.

After cutover, rollback the lexical profile to legacy-en on the NEW collection
if needed: new ingestions retain both fields. Returning to the old collection
after new writes requires reconciliation; this script never deletes either one.
"""

import argparse
import json

from qdrant_client.models import Modifier, SparseVectorParams

from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client
from app.rag.sparse_migration import (
    FRENCH_COLLECTION,
    build_sparse_profile,
    sparse_coverage,
    verify_sparse_copy,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["report", "build", "verify", "legacy-idf"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-points", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--target", default=FRENCH_COLLECTION)
    parser.add_argument("--offset")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    client = get_qdrant_client()
    if args.apply and args.phase == "build":
        result = build_sparse_profile(
            client,
            max_points=args.max_points,
            batch_size=args.batch_size,
            target=args.target,
            offset=args.offset,
            resume=args.resume,
        )
    elif args.phase == "verify":
        result = verify_sparse_copy(client, target=args.target)
    elif args.apply and args.phase == "legacy-idf":
        changed = client.update_collection(
            COLLECTION_NAME,
            sparse_vectors_config={
                "sparse-bm25": SparseVectorParams(modifier=Modifier.IDF),
            },
        )
        config = client.get_collection(COLLECTION_NAME).config.params.sparse_vectors or {}
        if not changed or config["sparse-bm25"].modifier != Modifier.IDF:
            raise RuntimeError("IDF configuration change not confirmed")
        result = {"collection": COLLECTION_NAME, "idf_enabled": True}
    else:
        result = sparse_coverage(client, args.target)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
