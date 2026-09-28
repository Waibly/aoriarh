"""Reading contracts, access isolation and follow-up execution; no generated quality checks."""
# ruff: noqa: F811

import json
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Message
from app.rag.agent import RagTrace
from app.rag.legal_catalogue import LegalCatalogueSearch
from app.rag.legal_source_reader import MAX_READ_CHARACTERS, read_legal_sources
from app.rag.parent_expansion import RetrievalError
from app.rag.search import HybridSearch
from app.services.conversation_history import planner_history
from app.services.conversation_orchestrator import prepare_conversation_context
from app.services.conversation_requests import decode_requests
from tests.conftest import test_session_factory
from tests.test_conversation_documents import conversation, task_payload
from tests.test_conversation_orchestrator import planner
from tests.test_conversation_requests import request, wire
from tests.test_document_extraction_service import dossier as dossier
from tests.test_legal_catalogue import document, insert, spec


def points(doc, count=7):
    return [
        SimpleNamespace(
            payload={
                "document_id": str(doc.id),
                "organisation_id": "common",
                "source_type": doc.source_type,
                "doc_name": doc.name,
                "chunk_index": index,
                "text": f"  Passage intégral {index}\n",
            }
        )
        for index in range(count)
    ]


async def test_read_orders_all_passages_and_filters_both_stores():
    doc = document(
        "arrêt",
        source_type="arret_cour_cassation",
        chunk_count=7,
        date_decision=date(2026, 9, 16),
        publication_date=date(2026, 9, 17),
        source_url="https://example.test/source",
    )
    await insert(doc)
    client = MagicMock()
    client.scroll.return_value = (list(reversed(points(doc))), None)
    async with test_session_factory() as db:
        results, coverage = await read_legal_sources(db, [doc.id], client=client)
    assert results[0].context_chunk_indices == list(range(7))
    assert results[0].text == "\n\n".join(p.payload["text"] for p in points(doc))
    assert coverage[0]["reading_scope"] == "all_indexed_passages"
    assert results[0].publication_date == "2026-09-17"
    assert results[0].date_decision == "2026-09-16"
    assert results[0].source_url == doc.source_url
    filters = client.scroll.call_args.kwargs["scroll_filter"].must
    assert {f.key: f.match.value for f in filters} == {
        "document_id": str(doc.id),
        "organisation_id": "common",
        "source_type": "arret_cour_cassation",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"organisation_id": uuid.uuid4()},
        {"indexation_status": "pending"},
        {"source_type": "divers"},
        {"source_type": "convention_collective_nationale"},
    ],
)
async def test_document_id_never_grants_access(changes):
    doc = document("excluded", **changes)
    await insert(doc)
    client = MagicMock()
    async with test_session_factory() as db:
        with pytest.raises(RetrievalError, match="legal_source_unavailable"):
            await read_legal_sources(db, [doc.id], client=client)
    client.scroll.assert_not_called()


@pytest.mark.parametrize(
    "policy",
    [
        {"source_exclusions": ["decret"]},
        {"source_restriction": ["loi"]},
    ],
)
async def test_explicit_source_policy_is_respected(policy):
    doc = document("excluded")
    await insert(doc)
    async with test_session_factory() as db:
        with pytest.raises(RetrievalError, match="legal_source_unavailable"):
            await read_legal_sources(db, [doc.id], client=MagicMock(), **policy)


@pytest.mark.parametrize("failure", ["missing", "gap", "private_payload", "budget", "next_page"])
async def test_incomplete_or_oversized_reads_are_errors_without_partial_substitution(failure):
    doc = document("arrêt", chunk_count=7)
    await insert(doc)
    found = points(doc)
    if failure == "missing":
        found.pop()
    elif failure == "gap":
        found[-1].payload["chunk_index"] = 8
    elif failure == "private_payload":
        found[-1].payload["organisation_id"] = str(uuid.uuid4())
    elif failure == "budget":
        found[-1].payload["text"] = "x" * MAX_READ_CHARACTERS
    client = MagicMock()
    client.scroll.return_value = (found, "next" if failure == "next_page" else None)
    async with test_session_factory() as db:
        with pytest.raises(RetrievalError):
            await read_legal_sources(db, [doc.id], client=client)
    assert client.scroll.call_count == 1


def test_old_invalid_dependency_is_not_reinterpreted_or_repaired():
    raw = wire([request("read", "read_one", source_request_id=str(uuid.uuid4()))])
    plan, _, _, errors = decode_requests(raw, previous=[], query="Q", continuation=False)
    assert not plan.actions
    assert errors[0]["error"] == "invalid_request_dependency"


async def test_catalogue_then_object_then_detail_reads_source_again(dossier, monkeypatch):
    """Three typed planner outputs; real catalogue, reader, dossier and source history."""
    doc = document(
        "Cass. soc., n° 25-15.456",
        source_type="arret_cour_cassation",
        date_decision=date(2026, 9, 16),
        numero_pourvoi="25-15.456",
        chunk_count=7,
    )
    await insert(doc)
    all_points = points(doc)
    qdrant = MagicMock()

    def scroll(**kwargs):
        for clause in kwargs["scroll_filter"].must:
            if getattr(clause, "key", None) == "chunk_index":
                return [p for p in all_points if p.payload["chunk_index"] in clause.match.any], None
        return list(reversed(all_points)), None

    qdrant.scroll.side_effect = scroll
    monkeypatch.setattr("app.rag.legal_source_reader.get_qdrant_client", lambda: qdrant)
    engine = HybridSearch.__new__(HybridSearch)
    engine.qdrant = qdrant
    catalogue = LegalCatalogueSearch(engine, None, session_factory=test_session_factory)
    chronology = spec(date_kind="decision", source_types=["arret_cour_cassation"])

    async def legal_search(*args, **kwargs):
        results, coverage = await catalogue.search(chronology, str(dossier.org.id))
        return results, "Q", RagTrace(search_plan_validation={"chronology": coverage})

    conv, _ = await conversation(dossier)
    history_messages = []
    raws = [
        wire(
            [
                request(
                    "legal",
                    "list_sources",
                    search=task_payload("documents_and_law")["legal_search"],
                )
            ]
        ),
        wire([request("read_legal_sources", "read_objects", document_ids=[str(doc.id)])]),
        wire(
            [
                request("read_legal_sources", "read_detail", document_ids=[str(doc.id)]),
                request(id="explain", depends_on=["read_detail"]),
            ]
        ),
    ]
    for index, raw in enumerate(raws):
        msg = Message(
            conversation_id=conv.id, role="user", content=["Liste", "Objet", "Détail"][index]
        )
        dossier.db.add(msg)
        await dossier.db.commit()
        agent = planner(raw)
        prepared = await prepare_conversation_context(
            agent,
            db=dossier.db,
            conversation=conv,
            user=dossier.user,
            query=msg.content,
            references=[],
            documents=[],
            document_continuity="",
            history=planner_history(history_messages),
            legal_search=legal_search,
            model="test",
            source_message_id=msg.id,
        )
        assert prepared.trace.error is None
        assert not prepared.trace.search_plan_validation.get("request_errors")
        assert prepared.trace.router_raw_response == raw
        assert all(
            task["status"] == "ready_for_generation" for task in prepared.case_context["tasks"]
        )
        expected_indices = list(range(6 if index == 0 else 7))
        assert prepared.results[0].context_chunk_indices == expected_indices
        if index:
            sent = json.loads(
                agent.llm.chat.completions.create.await_args.kwargs["messages"][1]["content"]
            )
            assert sent["history"][-1]["sources"][0]["document_id"] == str(doc.id)
        history_messages.append(
            SimpleNamespace(
                role="assistant",
                content="Réponse originale inchangée",
                created_at=datetime.now(UTC),
                rag_trace=prepared.trace.to_dict(),
                sources=[
                    {
                        "document_id": source.document_id,
                        "document_name": source.document_name,
                        "source_type": source.source_type,
                    }
                    for source in agent.format_sources(prepared.results)
                ],
            )
        )


async def test_failed_read_blocks_dependent_task_but_keeps_independent_task(dossier):
    conv, _ = await conversation(dossier)
    msg = Message(conversation_id=conv.id, role="user", content="Lire puis expliquer")
    dossier.db.add(msg)
    await dossier.db.commit()
    raw = wire(
        [
            request("read_legal_sources", "read_one", document_ids=[str(dossier.doc.id)]),
            request(id="dependent", depends_on=["read_one"]),
            request(id="independent"),
        ]
    )
    search = AsyncMock()
    prepared = await prepare_conversation_context(
        planner(raw),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=msg.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=search,
        model="test",
        source_message_id=msg.id,
    )
    assert prepared.results == []
    assert [t["status"] for t in prepared.case_context["tasks"]] == [
        "blocked",
        "blocked",
        "ready_for_generation",
    ]
    assert prepared.case_context["consultations"][0]["error"] == "legal_source_unavailable"
    assert prepared.trace.router_raw_response == raw
    search.assert_not_called()
