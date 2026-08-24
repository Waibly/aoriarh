"""Point d'entrée commun du pipeline RAG utilisé par les produits AORIA RH."""

from __future__ import annotations

from app.rag.agent import RAGAgent, RagTrace
from app.rag.search import SearchResult


async def prepare_rag_context(
    agent: RAGAgent,
    *,
    query: str,
    organisation_id: str,
    org_context: dict[str, str | None] | None = None,
    history: list[dict[str, str]] | None = None,
    cited_sources: list[str] | None = None,
    org_idcc_list: list[str] | None = None,
    user_id: str | None = None,
    context_id: str | None = None,
    is_replay: bool = False,
) -> tuple[list[SearchResult], str, RagTrace]:
    """Prépare les sources avec le pipeline adaptatif de production.

    Le chat, le sandbox, la recherche admin et les générateurs éditoriaux
    passent tous ici. Les différences entre produits commencent uniquement
    après la sélection et la validation des sources.
    """

    return await agent.prepare_context(
        query=query,
        organisation_id=organisation_id,
        org_context=org_context,
        history=history,
        cited_sources=cited_sources,
        org_idcc_list=org_idcc_list,
        user_id=user_id,
        conversation_id=context_id,
        is_replay=is_replay,
        adaptive_search=True,
    )
