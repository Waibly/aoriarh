"""Technical retrieval contracts across arbitrary sources; no generated-answer judge."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from qdrant_client import QdrantClient, models

from app.rag.agent import RAGAgent
from app.rag.jurisprudence_chunker import JurisprudenceChunker
from app.rag.lexical_profile import lexical_profile
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.reranker import VoyageReranker, build_rerank_query
from app.rag.search import HybridSearch, SearchResult
from app.rag.search_instructions import LEGAL_RETRIEVAL_INSTRUCTIONS
from app.rag.search_plan import (
    _COMPACT_PLANNER_PROMPT,
    AnswerIntent,
    build_deterministic_search_plan,
)
from app.rag.sparse_migration import (
    FRENCH_COLLECTION,
    build_sparse_profile,
    verify_sparse_copy,
)
from app.rag.temporal_parameters import user_period_parameters_available
from app.services.conversation_document_service import DocumentLegalSearch, continuity_history
from app.services.conversation_orchestrator import legal_plan
from app.services.conversation_requests import REQUEST_PROMPT, request_schema
from app.services.judilibre_service import JudilibreService
from app.services.judilibre_source import official_summaries, render_judilibre_source


def item(doc):
    return SearchResult("Source originale", doc, doc, "arret_cour_cassation", 4, 1, 0, .5)


def test_every_planner_receives_the_same_retrieval_guidance():
    assert LEGAL_RETRIEVAL_INSTRUCTIONS in REQUEST_PROMPT
    assert LEGAL_RETRIEVAL_INSTRUCTIONS in _COMPACT_PLANNER_PROMPT


def test_assistant_dates_cannot_enable_period_parameters():
    question = "Existe-t-il une autre décision comparable ?"
    history = [{"role": "assistant", "content": "Arrêt du 16 avril 2026."}]
    assert not user_period_parameters_available(question, history)
    schema = request_schema(2, period_parameters_available=False)
    properties = schema["$defs"]["ChronologyRequest"]["properties"]
    assert properties["date_from"] == properties["date_to"] == {"type": "null"}
    assert properties["period_basis"]["enum"] == ["none"]
    assert schema["$defs"]["RequestLegalSearch"]["properties"]["decision_period"] == {
        "type": "null",
    }


@pytest.mark.parametrize("question", [
    "Jurisprudence de 2025", "Depuis hier", "Les 90 derniers jours",
    "En septembre", "Since last week", "Depuis notre dernier échange",
    "Depuis la date indiquée dans le contrat", "Au 12/03",
])
def test_user_calendar_and_relative_periods_remain_available(question):
    assert user_period_parameters_available(question)


def test_user_history_can_authorize_a_period_without_assistant_prose():
    assert user_period_parameters_available("Et les autres juridictions ?", [
        {"role": "user", "content": "Décisions rendues en 2025"},
    ])
    continuity = "Consignes\nHistorique original (JSON) :" + json.dumps([
        {"role": "user", "content": "Décisions en 2025"},
        {"role": "assistant", "content": "Autre date : 2026"},
    ])
    assert user_period_parameters_available("Et les autres cours ?", continuity_history(continuity))


def test_orchestration_preserves_original_and_generated_branch_separately():
    original, generated = "Demande initiale 123\nintégrale", "Question autonome 456"
    args = DocumentLegalSearch(
        standalone_question=generated, needs_history=True, legal_topics=[],
        search_queries=["une requête"], hypothesized_articles=[], source_hints=[],
        jurisprudence="required", answer_intent=AnswerIntent.YES_NO, missing_facts=[],
    )
    planned = SimpleNamespace(legal_base=build_deterministic_search_plan(original),
                              requests=[], raw="sortie brute")
    plan = legal_plan(planned, SimpleNamespace(legal_search=args, query=generated, id="law"))
    assert plan.query_original == original
    assert plan.standalone_question == generated
    data = json.loads(build_rerank_query(plan.query_original, None, plan.standalone_question)
                      .split("\n", 1)[1])
    assert data["question_originale"] == original
    assert data["question_autonome"] == generated


async def test_variant_union_keeps_matches_unique_to_a_single_branch():
    obj = RAGAgent.__new__(RAGAgent)
    obj.search_engine = MagicMock()
    obj._org_id = "org"
    obj._user_id = obj._conversation_id = None
    obj._is_replay = True
    obj.search_engine.search = AsyncMock(side_effect=lambda q, *a, **kw: [
        item(f"{q}-{i}") for i in range(20)
    ])
    pool = await obj._run_variant_searches(["a", "b", "c"], "a", "org",
                                          apply_legislation_floor=False)
    assert len(pool) == 60
    assert {r.document_id for r in pool} == {f"{q}-{i}" for q in "abc" for i in range(20)}
    assert all(c.kwargs["candidate_pool"] for c in obj.search_engine.search.await_args_list)


@pytest.fixture
def vector_index():
    client = QdrantClient(":memory:")
    client.create_collection(
        COLLECTION_NAME, vectors_config={
            "dense": models.VectorParams(size=2, distance=models.Distance.COSINE),
        }, sparse_vectors_config={"sparse-bm25": models.SparseVectorParams()},
    )
    client.upsert(COLLECTION_NAME, points=[
        models.PointStruct(id=i, vector={
            "dense": [1.0, .01 * i] if i < 20 else [0.0, 1.0],
            "sparse-bm25": models.SparseVector(indices=[2 if i < 20 else 1], values=[1.0]),
        }, payload={"text": f"texte {i}", "document_id": str(i), "chunk_index": 0,
                    "organisation_id": "common" if i < 40 else "other-org",
                    "source_type": "arret_cour_cassation"}) for i in range(41)
    ])
    yield client
    client.close()


async def test_channel_union_preserves_dense_and_lexical_candidates_and_access(vector_index):
    engine = HybridSearch.__new__(HybridSearch)
    engine.qdrant = vector_index
    engine._encode_dense = AsyncMock(return_value=[1.0, 0.0])
    engine._encode_sparse_sync = lambda text: {"indices": [1], "values": [1.0]}
    found = await engine.search("demande", "org", top_k=20, candidate_pool=True)
    assert {r.document_id for r in found} == {str(i) for i in range(40)}
    assert "40" not in {r.document_id for r in found}
    directed = await engine.search("demande", "org", top_k=20, candidate_pool=True,
                                   source_type_filter=["code_travail"])
    assert directed == []


async def test_one_channel_failure_is_not_hidden_by_other_channels(vector_index):
    engine = HybridSearch.__new__(HybridSearch)
    engine.qdrant = MagicMock(wraps=vector_index)
    original = vector_index.query_points

    def query(*args, **kwargs):
        if kwargs.get("using") == "dense":
            raise RuntimeError("dense offline")
        return original(*args, **kwargs)

    engine.qdrant.query_points.side_effect = query
    engine._encode_dense = AsyncMock(return_value=[1., 0.])
    engine._encode_sparse_sync = lambda text: {"indices": [1], "values": [1.]}
    with pytest.raises(RuntimeError, match="dense offline"):
        await engine.search("question", "org", candidate_pool=True)


def test_query_uses_query_encoding_and_profiles_have_distinct_vector_names(monkeypatch):
    model = MagicMock()
    model.query_embed.return_value = [SimpleNamespace(
        indices=np.array([1]), values=np.array([1.]),
    )]
    monkeypatch.setattr("app.rag.search._get_sparse_model", lambda: model)
    assert HybridSearch.__new__(HybridSearch)._encode_sparse_sync("brut") == {
        "indices": [1], "values": [1.],
    }
    model.query_embed.assert_called_once_with(["brut"])
    model.embed.assert_not_called()
    assert lexical_profile("legacy-en").vector_name != lexical_profile("french-v1").vector_name


def french_model():
    return SimpleNamespace(embed=lambda texts: [SimpleNamespace(
        indices=np.array([3]), values=np.array([1.]),
    ) for _ in texts])


def test_sparse_copy_is_resumable_preserves_old_data_and_checks_coverage(vector_index):
    original, _ = vector_index.scroll(COLLECTION_NAME, limit=100, with_vectors=True)
    first = build_sparse_profile(vector_index, max_points=9, batch_size=3, model=french_model())
    assert first["processed"] == 9
    assert not first["complete"]
    assert first["source_points"] == 41
    with pytest.raises(ValueError, match="explicit_resume"):
        build_sparse_profile(vector_index, max_points=1, model=french_model())
    with pytest.raises(ValueError, match="incomplete_copy"):
        verify_sparse_copy(vector_index)
    second = build_sparse_profile(vector_index, max_points=100, batch_size=7,
                                  offset=first["next_offset"], model=french_model(), resume=True)
    assert second["next_offset"] is None
    assert verify_sparse_copy(vector_index)["verified_points"] == 41
    after, _ = vector_index.scroll(COLLECTION_NAME, limit=100, with_vectors=True)
    assert after == original
    assert vector_index.get_collection(FRENCH_COLLECTION).config.params.sparse_vectors[
        "sparse-bm25-fr-v1"
    ].modifier == models.Modifier.IDF
    vector_index.set_payload(FRENCH_COLLECTION, {"organisation_id": "wrong"}, points=[0])
    with pytest.raises(ValueError, match="payload_or_identity_mismatch"):
        verify_sparse_copy(vector_index)


def test_sparse_copy_refuses_active_collection_and_missing_source_text(vector_index):
    with pytest.raises(ValueError, match="destination"):
        build_sparse_profile(vector_index, max_points=1, target=COLLECTION_NAME)
    vector_index.delete_payload(COLLECTION_NAME, keys=["text"], points=[0])
    with pytest.raises(ValueError, match="missing_source_text"):
        build_sparse_profile(vector_index, max_points=2, model=french_model())


def test_all_official_summaries_and_original_body_survive_source_preparation():
    raw = {"text": "  Corps original\nFaits et procédure\nfaits\nRéponse de la Cour\nmotifs\n",
           "summary": "  Sommaire A\n", "titlesAndSummaries": [
               {"titles": ["Titre officiel"], "summary": "  Sommaire A\n"},
               {"titles": ["Autre titre"], "summary": "Sommaire B"},
           ]}
    rendered = render_judilibre_source(raw)
    assert rendered.endswith(raw["text"])
    assert official_summaries(raw) == ["  Sommaire A\n", "Sommaire B"]
    assert all(s in rendered for s in official_summaries(raw))
    assert all(title in rendered for title in ["Titre officiel", "Autre titre"])
    chunks = JurisprudenceChunker().chunk(rendered)
    assert any("[Sommaire officiel]" in text and "Sommaire B" in text for text in chunks)
    assert not any("Sommaire A" in text and "Sommaire B" in text for text in chunks)
    parsed = JudilibreService._parse_decision({**raw, "decision_date": "2026-01-01"})
    assert parsed.raw_source == raw | {"decision_date": "2026-01-01"}
    assert "Sommaire B" in parsed.sommaire


def test_absent_official_summary_preserves_body_and_invalid_types_are_errors():
    raw = {"text": "  corps intégral\n", "summary": None, "titlesAndSummaries": None}
    assert render_judilibre_source(raw) == raw["text"]
    with pytest.raises(ValueError, match="invalid_official_summary_structure"):
        render_judilibre_source({**raw, "summary": ["wrong protocol type"]})


async def test_reranker_scores_full_larger_union_in_bounded_batches():
    rr = VoyageReranker()

    async def score(query, documents):
        return {"data": [{"index": i, "relevance_score": .5}
                         for i in range(len(documents))]}

    rr._call_api = AsyncMock(side_effect=score)
    candidates = [item(str(i)) for i in range(145)]
    ranked = await rr.rerank("question", candidates)
    assert {r.document_id for r in ranked} == {str(i) for i in range(145)}
    assert [len(call.args[1]) for call in rr._call_api.await_args_list] == [64, 64, 17]
    assert all(r.text == "Source originale" for r in ranked)


async def test_reranker_batch_failure_does_not_produce_partial_ranking():
    rr = VoyageReranker()
    rr._call_api = AsyncMock(side_effect=[
        {"data": [{"index": i, "relevance_score": .5} for i in range(64)]},
        RuntimeError("offline"),
    ])
    with pytest.raises(Exception, match="unavailable"):
        await rr.rerank("question", [item(str(i)) for i in range(65)])
