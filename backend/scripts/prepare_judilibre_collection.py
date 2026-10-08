"""Move existing vectors/indexes to disk before the CA backfill.

Run without --apply for a read-only report. No recreation, deletion, model or
vector dimension change. Qdrant rebuilds affected indexes in the background.
"""

import argparse
import json

from qdrant_client.models import (
    HnswConfigDiff,
    OptimizersConfigDiff,
    SparseIndexParams,
    SparseVectorParams,
    VectorParamsDiff,
)

from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = get_qdrant_client()
    before = client.get_collection(COLLECTION_NAME)
    print(
        json.dumps(
            {
                "phase": "before",
                "points": before.points_count,
                "config": before.config.model_dump(mode="json"),
            }
        )
    )
    if args.apply:
        result = client.update_collection(
            COLLECTION_NAME,
            vectors_config={"dense": VectorParamsDiff(on_disk=True)},
            sparse_vectors_config={
                "sparse-bm25": SparseVectorParams(index=SparseIndexParams(on_disk=True))
            },
            hnsw_config=HnswConfigDiff(on_disk=True, max_indexing_threads=2),
            optimizers_config=OptimizersConfigDiff(max_optimization_threads=1),
        )
        if not result:
            raise RuntimeError("Qdrant a refusé la mise à jour de configuration")
        after = client.get_collection(COLLECTION_NAME)
        assert after.config.params.vectors["dense"].on_disk is True
        assert after.config.params.sparse_vectors["sparse-bm25"].index.on_disk is True
        print(
            json.dumps(
                {
                    "phase": "after",
                    "status": str(after.status),
                    "points": after.points_count,
                    "config": after.config.model_dump(mode="json"),
                }
            )
        )


if __name__ == "__main__":
    main()
