"""Attribution des coûts API sous concurrence multi-tenant.

HybridSearch et VoyageReranker sont des singletons partagés entre toutes les
requêtes. Le contexte de coût (org/user/question) doit leur être passé PAR
APPEL (CostContext) et jamais stocké sur l'instance : deux questions
simultanées de deux organisations s'écraseraient mutuellement et les coûts
seraient facturés à la mauvaise org (race relevée à l'audit du 27/07/2026).

Ces tests exécutent des appels réellement CONCURRENTS sur la même instance
partagée et vérifient que chaque coût part avec l'organisation de SA requête.
"""
from __future__ import annotations

import asyncio

from app.rag.reranker import VoyageReranker
from app.rag.search import HybridSearch, SearchResult
from app.services.cost_tracker import CostContext


def _res(i: int) -> SearchResult:
    return SearchResult(
        text=f"texte {i}",
        doc_name="doc",
        document_id=f"doc-{i}",
        source_type="code_travail",
        norme_niveau=2,
        norme_poids=1.0,
        chunk_index=0,
        score=0.5,
    )


async def test_concurrent_rerank_costs_attributed_to_each_org(monkeypatch):
    logged: list[dict] = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr("app.rag.reranker.cost_tracker.log", fake_log)

    async def fake_api(self, query, documents):
        # Chevauchement garanti : les deux appels sont en vol en même temps.
        await asyncio.sleep(0.05)
        return {
            "usage": {"total_tokens": 42},
            "data": [
                {"index": i, "relevance_score": 0.9}
                for i in range(len(documents))
            ],
        }

    monkeypatch.setattr(VoyageReranker, "_call_api", fake_api)

    reranker = VoyageReranker()  # une seule instance, comme le singleton prod
    await asyncio.gather(
        reranker.rerank(
            "q A", [_res(1), _res(2)], top_k=2,
            cost_ctx=CostContext(organisation_id="org-A", context_id="question-A"),
        ),
        reranker.rerank(
            "q B", [_res(3), _res(4)], top_k=2,
            cost_ctx=CostContext(organisation_id="org-B", context_id="question-B"),
        ),
    )

    assert len(logged) == 2
    by_question = {kw["context_id"]: kw["organisation_id"] for kw in logged}
    assert by_question == {"question-A": "org-A", "question-B": "org-B"}


async def test_concurrent_embeddings_attributed_to_each_org(monkeypatch):
    logged: list[dict] = []

    async def fake_log(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr("app.rag.search.cost_tracker.log", fake_log)

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {
                "data": [{"embedding": [0.0] * 1024}],
                "usage": {"total_tokens": 7},
            }

    async def fake_post(self, url, **kwargs):
        await asyncio.sleep(0.05)
        return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    engine = HybridSearch.__new__(HybridSearch)  # sans connexion Qdrant
    await asyncio.gather(
        engine._encode_dense(
            "texte A",
            CostContext(organisation_id="org-A", context_id="question-A"),
        ),
        engine._encode_dense(
            "texte B",
            CostContext(organisation_id="org-B", context_id="question-B"),
        ),
    )

    assert len(logged) == 2
    by_question = {kw["context_id"]: kw["organisation_id"] for kw in logged}
    assert by_question == {"question-A": "org-A", "question-B": "org-B"}
