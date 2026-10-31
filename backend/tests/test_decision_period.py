"""Real retrieval/filter regressions; no evaluation of generated legal answers."""

import json
import uuid
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from app.models.document import Document
from app.rag.agent import RAGAgent
from app.rag.chronology import ChronologyRequest
from app.rag.decision_period import DecisionPeriod
from app.rag.legal_catalogue import catalogue_page
from app.rag.parent_expansion import fetch_by_identifiers
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.search import HybridSearch
from app.rag.search_plan import (
    apply_compact_planner_payload,
    build_deterministic_search_plan,
    run_compact_search_planner,
)
from app.services.conversation_requests import RequestLegalSearch, request_schema
from tests.conftest import test_session_factory as session_factory

PERIOD = {
    "date_from": "2025-01-01",
    "date_to": "2025-12-31",
    "period_basis": "explicit",
    "source_types": [],
}


def arguments(**changes):
    return {
        "needs_history": False,
        "legal_topics": ["thème demandé"],
        "search_queries": ["question de droit"],
        "hypothesized_articles": [],
        "source_hints": ["legislation", "jurisprudence"],
        "jurisprudence": "required",
        "answer_intent": "yes_no",
        "missing_facts": [],
        "chronology": None,
        "decision_period": PERIOD,
        **changes,
    }


def plan_for(question):
    wire = RequestLegalSearch.model_validate_json(json.dumps(arguments()))
    return apply_compact_planner_payload(
        build_deterministic_search_plan(question),
        {**wire.model_dump(mode="json"), "standalone_question": question},
    )


@pytest.fixture
def index():
    client = QdrantClient(":memory:")
    client.create_collection(
        COLLECTION_NAME,
        vectors_config={"dense": VectorParams(size=2, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse-bm25": SparseVectorParams()},
    )
    yield client
    client.close()


def point(key, *, source_type="arret_cour_cassation", when=None, org="common", **extra):
    return PointStruct(
        id=key,
        vector={
            "dense": [1.0, 0.0],
            "sparse-bm25": SparseVector(indices=[1], values=[1.0]),
        },
        payload={
            "document_id": str(key),
            "doc_name": f"Document {key}",
            "organisation_id": org,
            "source_type": source_type,
            "date_decision": when,
            "chunk_index": 0,
            "text": f"Texte original {key}\n\nFIN",
            **extra,
        },
    )


def selected_ids(client, **kwargs):
    search = HybridSearch.__new__(HybridSearch)
    scope = search._build_org_filter("org", decision_period=PERIOD, **kwargs)
    return {p.id for p in client.scroll(COLLECTION_NAME, scroll_filter=scope, limit=100)[0]}


def test_period_uses_decision_date_includes_entire_end_day_and_keeps_other_sources(index):
    index.upsert(
        COLLECTION_NAME,
        [
            point(0, when="2025-01-01T00:00:00Z"),
            point(1, when="2025-12-31T23:59:59Z"),
            point(2, when="2024-12-31T23:59:59Z", content_date="2025-03-19"),
            point(3, when="2026-01-01T00:00:00Z"),
            point(4, content_date="2025-03-19"),
            point(5, source_type="code_travail", when="2008-05-01T00:00:00Z"),
            point(6, source_type="accord_entreprise", org="org"),
            point(7, source_type="accord_entreprise", org="other-org"),
            point(8, when="2025-03-19T00:00:00Z", org="other-org"),
            point(9, source_type="convention_collective_nationale", idcc="1486"),
        ],
    )
    assert selected_ids(index) == {0, 1, 5, 6}
    assert selected_ids(index, org_idcc_list=["1486"]) == {0, 1, 5, 6, 9}
    assert selected_ids(index, source_type_filter=["arret_cour_cassation"]) == {0, 1}
    assert selected_ids(index, document_ids=["7"]) == set()
    assert selected_ids(index, excluded_source_types=["accord_entreprise"]) == {0, 1, 5}


async def test_exact_references_obey_period_without_filtering_older_law(index):
    index.upsert(
        COLLECTION_NAME,
        [
            point(0, when="2025-03-19T00:00:00Z", numero_pourvoi="23-19.154"),
            point(1, when="2024-03-19T00:00:00Z", numero_pourvoi="23-19.154"),
            point(2, source_type="code_travail", article_nums=["L3121-36"]),
        ],
    )
    results = await fetch_by_identifiers(
        index,
        {"numero_pourvoi": ["23-19.154"], "article_nums": ["L3121-36"]},
        "org",
        decision_period=PERIOD,
    )
    assert {r.document_id for r in results} == {"0", "2"}


@pytest.mark.parametrize(
    "changes",
    [
        {"date_from": None, "date_to": None},
        {"date_from": "2025-12-31", "date_to": "2025-01-01"},
        {"period_basis": "none"},
        {"source_types": ["code_travail"]},
    ],
)
def test_invalid_period_is_a_technical_error(changes):
    with pytest.raises(ValidationError):
        DecisionPeriod.model_validate_json(json.dumps({**PERIOD, **changes}))


def test_typed_request_preserves_period_and_rejects_simultaneous_catalogue_operation():
    plan = plan_for("Une question de droit fondée sur la jurisprudence de 2025")
    assert plan.to_dict()["decision_period"] == PERIOD
    assert plan.chronology is None
    schema = request_schema(2)
    assert "decision_period" in schema["$defs"]["RequestLegalSearch"]["required"]
    chronological = {
        "date_kind": "decision",
        **PERIOD,
        "jurisdiction": None,
        "chamber": None,
        "topic": None,
        "order": "newest",
        "limit": 5,
        "offset": 0,
    }
    with pytest.raises(ValidationError, match="conflicting_search_operations"):
        RequestLegalSearch.model_validate_json(json.dumps(arguments(chronology=chronological)))


async def test_invalid_planner_operation_keeps_original_output_without_retry():
    wire = arguments(decision_period={**PERIOD, "date_to": "2024-01-01"})
    wire["standalone_question"] = "Question de droit"
    raw = json.dumps(wire, ensure_ascii=False)
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw))],
            usage=None,
        )
    )
    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = await run_compact_search_planner(
        build_deterministic_search_plan("Quelle jurisprudence de 2025 ?"),
        llm=llm,
        model="model-test",
    )
    assert result.plan.planner_status.value == "error"
    assert result.plan.planner_raw_response == raw
    assert create.await_count == 1


@pytest.mark.parametrize(
    ("question", "number", "when"),
    [
        (
            "Un employeur licencie un manager pour harcèlement moral en s'appuyant sur plusieurs "
            "témoignages anonymisés de salariés. Le manager conteste leur valeur probante. "
            "Ces témoignages peuvent-ils être retenus par le juge ? "
            "Que prévoit la jurisprudence de 2025 ?",
            "23-19.154",
            date(2025, 3, 19),
        ),
        (
            "Un salarié travaille 31 heures dans une semaine et prend 7 heures de congés payés. "
            "Son contrat prévoit 35 heures hebdomadaires. Peut-il bénéficier des majorations pour "
            "heures supplémentaires ? Appuye ta réponse sur la jurisprudence de 2025.",
            "23-14.455",
            date(2025, 9, 10),
        ),
    ],
)
async def test_full_context_retrieves_decision_beyond_500_newer_documents(
    index,
    question,
    number,
    when,
):
    # Real SQL catalogue and Qdrant retrieval. Only external encoders and reranker
    # are controlled; these tests measure document reachability, not legal quality.
    target_id, law_id = uuid.uuid4(), uuid.uuid4()
    documents, points = [], []
    for i in range(601):
        key = uuid.uuid4()
        documents.append(
            Document(
                id=key,
                name=f"Later decision {i}",
                storage_path=f"test/{key}",
                source_type="arret_cour_cassation",
                indexation_status="indexed",
                date_decision=date(2025, 12, 17),
                chambre="sociale",
                chunk_count=1,
            )
        )
        p = point(str(key), when="2025-12-17T00:00:00Z")
        p.vector = {"dense": [0.0, 1.0], "sparse-bm25": SparseVector(indices=[2], values=[1.0])}
        points.append(p)
    documents.append(
        Document(
            id=target_id,
            name=number,
            storage_path=f"test/{target_id}",
            source_type="arret_cour_cassation",
            indexation_status="indexed",
            date_decision=when,
            chambre="sociale",
            chunk_count=1,
            numero_pourvoi=number,
        )
    )
    points.extend(
        [
            point(str(target_id), when=f"{when.isoformat()}T00:00:00Z", numero_pourvoi=number),
            point(str(law_id), source_type="code_travail", content_date="2008-05-01"),
        ]
    )
    async with session_factory() as db:
        db.add_all(documents)
        await db.commit()
        previous, report = await catalogue_page(
            db,
            ChronologyRequest.model_validate_json(
                json.dumps(
                    {
                        "date_kind": "decision",
                        **PERIOD,
                        "source_types": ["arret_cour_cassation"],
                        "jurisdiction": None,
                        "chamber": "sociale",
                        "topic": "question de droit",
                        "order": "newest",
                        "limit": 5,
                        "offset": 0,
                    }
                )
            ),
        )
    assert report["topic_candidates_truncated"] is True
    assert len(previous) == 500
    assert target_id not in {doc.id for doc, _ in previous}
    index.upsert(COLLECTION_NAME, points)
    engine = HybridSearch.__new__(HybridSearch)
    engine.qdrant = index
    engine._encode_dense = AsyncMock(return_value=[1.0, 0.0])
    engine._encode_sparse_sync = lambda query: {"indices": [1], "values": [1.0]}

    async def retain_order(query, candidates, **kwargs):
        return candidates

    agent = RAGAgent.__new__(RAGAgent)
    agent.search_engine = engine
    agent.reranker = SimpleNamespace(rerank=AsyncMock(side_effect=retain_order))
    plan = plan_for(question)
    # Explicit typed periods also supersede a legacy whole-source time hint.
    plan = replace(plan, time_scope={"kind": "calendar_year", "year": 2025})
    results, _, trace = await agent.prepare_context(
        question,
        str(uuid.uuid4()),
        search_plan=plan,
    )
    assert trace.error is None
    by_id = {r.document_id: r for r in results}
    assert str(target_id) in by_id
    assert by_id[str(target_id)].numero_pourvoi == number
    assert by_id[str(target_id)].text == f"Texte original {target_id}\n\nFIN"
    assert str(law_id) in by_id
    assert "chronology" not in trace.search_plan_validation
    assert all(b.get("decision_period") == PERIOD for b in trace.search_plan_validation["branches"])
