from app.core.config import settings

EMBEDDING_MODEL = settings.voyage_embedding_model
LLM_MODEL = settings.llm_model

CHUNK_SIZE = 1024
CHUNK_OVERLAP = 100

TOP_K = 20
RERANK_TOP_K = 15
RERANK_MODEL = "rerank-2"

# Legislation floor: number of "written-law" candidates pulled by the auxiliary
# legislation-only retrieval and injected into the candidate pool, so codified
# articles always reach the reranker even when jurisprudence dominates the main
# hybrid search. The reranker still decides which (if any) make the final cut.
LEGISLATION_FLOOR_TOP = 5

CONDENSE_HISTORY_LIMIT = 6

RAG_TIMEOUT_GLOBAL = 120.0
RAG_TIMEOUT_PER_STEP = 60.0
RAG_MAX_ITERATIONS = 2
