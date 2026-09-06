"""Technical selection contracts: synthetic passages and an in-memory index."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.rag.agent import RAGAgent
from app.rag.parent_expansion import (
    MAX_CHARS_PER_GROUP,
    ParentExpansionError,
    _fetch_siblings,
    _merge_group,
    expand_to_parents,
)
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.reranker import RerankingError, VoyageReranker
from app.rag.search import SearchResult
from app.rag.search_feedback import search_feedback
from app.rag.search_plan import build_deterministic_search_plan


def result(doc="doc", index=0, score=0.8, text="original passage", articles=None):
    return SearchResult(text, doc, doc, "code_travail", 1, 1.0, index, score, article_nums=articles)


@pytest.fixture
def index():
    client = QdrantClient(":memory:")
    client.create_collection(
        COLLECTION_NAME, vectors_config=VectorParams(size=2, distance=Distance.COSINE)
    )
    yield client
    client.close()


def insert(index, count=140):
    index.upsert(
        COLLECTION_NAME,
        [
            PointStruct(
                id=i,
                vector=[1.0, 0.0],
                payload={
                    "document_id": "doc",
                    "organisation_id": "org",
                    "chunk_index": i,
                    "source_type": "code_travail",
                    "article_nums": ["1"],
                    "text": f"passage {i}",
                },
            )
            for i in range(count)
        ],
    )


async def test_seed_survives_paginated_fetch_limit_and_warning_is_visible(index):
    insert(index)
    seed = result(index=139, text="SELECTED ORIGINAL", articles=["1"])
    diagnostics = []
    groups = await expand_to_parents([seed], index, organisation_id="org", diagnostics=diagnostics)
    assert seed.text in groups[0].text
    assert groups[0].seed_text == seed.text
    assert diagnostics[0]["pages"] == 4
    assert diagnostics[0]["fetch_limited"] is True
    assert 139 in diagnostics[0]["context_indices"]
    feedback = search_feedback({"search_plan_validation": {"selection": {"groups": diagnostics}}})
    assert feedback["warnings"]


def test_window_is_filtered_on_index_not_first_scroll_page(index):
    insert(index)
    siblings, info = _fetch_siblings(index, ("window", "doc", 130))
    assert {r.chunk_index for r in siblings} == {128, 129, 130, 131, 132}
    assert info["fetch_limited"] is False


async def test_parent_lookup_preserves_tenant_and_ccn_access(index):
    payloads = [
        ("org", "code_travail", None),
        ("other", "code_travail", None),
        ("common", "convention_collective_nationale", "1486"),
        ("common", "convention_collective_nationale", "0413"),
    ]
    index.upsert(
        COLLECTION_NAME,
        [
            PointStruct(
                id=i,
                vector=[1.0, 0.0],
                payload={
                    "document_id": "doc",
                    "organisation_id": org,
                    "source_type": st,
                    "idcc": idcc,
                    "chunk_index": i,
                    "article_nums": ["1"],
                    "text": f"record {i}",
                },
            )
            for i, (org, st, idcc) in enumerate(payloads)
        ],
    )
    groups = await expand_to_parents(
        [result(articles=["1"])],
        index,
        organisation_id="org",
        org_idcc_list=["1486"],
    )
    assert "record 1" not in groups[0].text
    assert "record 3" not in groups[0].text
    assert "record 2" in groups[0].text


async def test_rerank_all_then_select_distinct_parents_without_rescue():
    pool = [result(index=i, articles=["1"]) for i in range(15)] + [result("other")]
    rr = VoyageReranker()
    rr._call_api = AsyncMock(
        return_value={"data": [{"index": i, "relevance_score": 1 - i * 0.01} for i in range(16)]}
    )
    ranked = await rr.rerank("q", pool)
    out = await expand_to_parents(ranked, SimpleNamespace(scroll=lambda **kw: ([], None)))
    assert [r.document_id for r in out] == ["doc", "other"]
    assert out[1].score == ranked[-1].score


async def test_no_legislation_or_ccn_quota_changes_rank():
    pool = [result(str(i), score=1 - i * 0.02) for i in range(12)]
    pool = [replace(r, source_type="arret_cour_cassation") for r in pool[:10]] + pool[10:]
    diagnostics = []
    out = await expand_to_parents(
        pool, SimpleNamespace(scroll=lambda **kw: ([], None)), diagnostics=diagnostics
    )
    assert [r.document_id for r in out] == [str(i) for i in range(10)]
    assert sum(d["status"] == "excluded_group_budget" for d in diagnostics) == 2


async def test_parent_failure_is_not_replaced_with_seeds():
    def broken(**kwargs):
        raise RuntimeError("simulated outage")

    with pytest.raises(ParentExpansionError, match="parent_fetch_failed"):
        await expand_to_parents([result()], SimpleNamespace(scroll=broken))


async def test_overlapping_windows_share_one_context_group():
    seeds = [result(index=0, text="first"), result(index=3, text="second")]
    out = await expand_to_parents(seeds, SimpleNamespace(scroll=lambda **kw: ([], None)))
    assert len(out) == 1
    assert out[0].text == "first\n\nsecond"


def test_budget_preserves_original_passages_without_reconstructing_content():
    seed = result(index=5, text="  exact original\n[Section]\nfin  ")
    other = result(index=4, text="x" * MAX_CHARS_PER_GROUP)
    merged = _merge_group([other], seed.score, [seed])
    assert merged.text == seed.text
    assert merged.context_chunk_indices == [5]
    with pytest.raises(ParentExpansionError, match="exceeds_context_budget"):
        _merge_group([], 0.9, [result(text="x" * (MAX_CHARS_PER_GROUP + 1))])


def test_versions_are_not_combined(index):
    index.upsert(
        COLLECTION_NAME,
        [
            PointStruct(
                id=i,
                vector=[1.0, 0.0],
                payload={
                    "document_id": "doc",
                    "chunk_index": i,
                    "article_nums": ["1"],
                    "instrument_id": instrument,
                    "text": instrument,
                },
            )
            for i, instrument in enumerate(["v1", "v2"])
        ],
    )
    found, _ = _fetch_siblings(index, ("article", "doc", "v1", "1"))
    assert [r.text for r in found] == ["v1"]


def test_history_uses_full_passages_and_does_not_assert_validity():
    agent = RAGAgent.__new__(RAGAgent)
    block = agent._build_carried_context(
        [
            {
                "document_name": "Source",
                "excerpt": "short preview",
                "full_text": "full evidence " * 100,
            }
        ]
    )
    assert "full evidence " * 100 in block
    assert "short preview" not in block
    assert "fondement VALIDE" not in block


def test_explicit_publication_period_has_no_out_of_period_fallback():
    plan = build_deterministic_search_plan("Nouveautés en droit social en 2024")
    old = replace(result("old"), content_date="2020-01-01")
    undated = result("undated")
    current = replace(result("requested"), content_date="2024-06-01")
    kept, excluded = RAGAgent._filter_publication_period([old, undated], plan)
    assert kept == []
    assert len(excluded) == 2
    kept, _ = RAGAgent._filter_publication_period([old, current], plan)
    assert kept == [current]
    assert current.score == 0.8


def test_persisted_passages_keep_complete_text_and_budget_notice():
    agent = RAGAgent.__new__(RAGAgent)
    first = result(text="x" * 6000)
    second = result(index=2, text="y" * 6000)
    source = agent.format_sources([first, second])[0]
    from dataclasses import asdict

    block = agent._build_carried_context([asdict(source)])
    assert first.text in block
    assert second.text not in block
    assert "1 groupe(s) historique(s) non joint(s)" in block


def test_oversized_historical_source_is_disclosed_not_sliced():
    agent = RAGAgent.__new__(RAGAgent)
    block = agent._build_carried_context([{"full_text": "x" * 10000}])
    assert "budget technique dépassé" in block
    assert "xxxx" not in block


@pytest.mark.parametrize("error", ["reranker", "parents"])
async def test_context_error_keeps_planner_trace_without_generation(error):
    agent = RAGAgent.__new__(RAGAgent)
    agent._fetch_identifiers = AsyncMock(return_value=[])
    agent.search_engine = SimpleNamespace(qdrant=None)
    agent.reranker = VoyageReranker()
    agent.reranker._call_api = AsyncMock(
        return_value={"data": [{"index": 0, "relevance_score": 0.8}]}
    )
    agent._search_with_plan = AsyncMock(return_value=([result()], ["q"]))
    agent._inject_legislation_floor = AsyncMock(side_effect=lambda pool, *a, **kw: pool)
    plan = build_deterministic_search_plan("L.1234-9")
    if error == "reranker":
        agent.reranker._call_api.side_effect = RerankingError("offline")
    with patch(
        "app.rag.agent.expand_to_parents",
        new=AsyncMock(side_effect=ParentExpansionError("offline")),
    ):
        out, _, trace = await agent.prepare_context("L.1234-9", "org", search_plan=plan)
    assert not out
    assert trace.error == (
        "search_reranking_error" if error == "reranker" else "search_context_error"
    )
    assert trace.search_plan is not None
