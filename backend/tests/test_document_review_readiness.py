"""Already-read attachments satisfy direct review, without changing the raw plan."""

# ruff: noqa: F811 -- shared pytest fixture import.
import json
from unittest.mock import AsyncMock

import pytest

from app.models.conversation import Message
from app.services.conversation_orchestrator import prepare_conversation_context
from tests.test_conversation_documents import conversation
from tests.test_conversation_orchestrator import planner
from tests.test_conversation_requests import request, wire
from tests.test_document_extraction_service import dossier as dossier


@pytest.mark.parametrize("continuity", ["", "Historique original intégral avec une pièce"])
async def test_attachment_continuity_keeps_structured_historical_source_references(
    dossier,
    continuity,
):
    conv, refs = await conversation(dossier)
    source_id = "20000000-0000-0000-0000-000000000001"
    source = {
        "document_id": source_id,
        "document_name": "Arrêt déjà cité",
        "source_type": "jurisprudence",
    }
    history = [{"role": "assistant", "content": "Réponse originale", "sources": [source]}]
    msg = Message(conversation_id=conv.id, role="user", content="Développe cet arrêt")
    dossier.db.add(msg)
    await dossier.db.commit()
    agent = planner(wire([request(task_type="document_review")]))
    prepared = await prepare_conversation_context(
        agent,
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=msg.content,
        references=refs,
        documents=[{**refs[0], "source_name": "Pièce", "text": "  Original\n", "coverage": {}}],
        document_continuity=continuity,
        history=history,
        legal_search=AsyncMock(),
        model="test",
        source_message_id=msg.id,
    )
    assert prepared.trace.error is None
    sent = agent.llm.chat.completions.create.await_args.kwargs
    schema = sent["response_format"]["json_schema"]["schema"]
    assert {"$ref": "#/$defs/ReadLegalSourcesRequest"} in (
        schema["properties"]["requests"]["items"]["anyOf"]
    )
    assert schema["$defs"]["ReadLegalSourcesRequest"]["properties"]["document_ids"]["items"][
        "enum"
    ] == [source_id]
    payload = json.loads(sent["messages"][1]["content"])
    if continuity:
        assert payload["history"] == continuity
        assert payload["history_source_references"] == [{"sources": [source]}]
    else:
        assert payload["history"] == history
    assert prepared.results[0].text == "  Original\n"
    agent.llm.chat.completions.create.assert_awaited_once()


@pytest.mark.parametrize(
    "task_type,has_documents,expected",
    [
        ("drafting", False, "ready_for_generation"),
        ("drafting", True, "ready_for_generation"),
        ("document_review", False, "blocked"),
        ("document_review", True, "ready_for_generation"),
        ("legal_question", False, "blocked"),
        ("legal_question", True, "blocked"),
    ],
)
async def test_direct_task_uses_actual_document_availability(
    dossier,
    task_type,
    has_documents,
    expected,
):
    conv, refs = await conversation(dossier)
    msg = Message(conversation_id=conv.id, role="user", content="Analyse les pièces fournies")
    dossier.db.add(msg)
    await dossier.db.commit()
    documents = (
        [
            {
                **refs[0],
                "source_name": "Pièce déjà lue",
                "text": "  Source originale\n",
                "coverage": {},
            }
        ]
        if has_documents
        else []
    )
    raw = wire([request(task_type=task_type)])
    agent = planner(raw)
    search = AsyncMock()
    prepared = await prepare_conversation_context(
        agent,
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=msg.content,
        references=refs if has_documents else [],
        documents=documents,
        document_continuity="",
        history=[],
        legal_search=search,
        model="test",
        source_message_id=msg.id,
    )
    assert prepared.trace.error is None
    assert prepared.case_context["tasks"][0]["status"] == expected
    assert prepared.case_context["tasks"][0]["type"] == task_type
    assert prepared.trace.router_raw_response == raw
    if has_documents:
        assert prepared.results[0].text == documents[0]["text"]
    agent.llm.chat.completions.create.assert_awaited_once()
    search.assert_not_awaited()


async def test_failed_explicit_consultation_still_blocks_review_of_pre_read_attachment(
    dossier,
    monkeypatch,
):
    conv, refs = await conversation(dossier)
    msg = Message(conversation_id=conv.id, role="user", content="Vérifie cette clause")
    dossier.db.add(msg)
    await dossier.db.commit()
    doc = {
        **refs[0],
        "source_name": "Pièce partielle",
        "text": "  Passage original\n",
        "coverage": {},
        "transmitted_scope": "targeted_passages",
    }
    read = AsyncMock(side_effect=TimeoutError("simulated attachment consultation failure"))
    monkeypatch.setattr(
        "app.services.conversation_document_service.read_conversation_documents",
        read,
    )
    raw = wire(
        [
            request("search_uploaded_passages", "consult", document_ids=[refs[0]["document_id"]]),
            request(task_type="document_review", depends_on=["consult"]),
        ]
    )
    agent = planner(raw)
    prepared = await prepare_conversation_context(
        agent,
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=msg.content,
        references=refs,
        documents=[doc],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
        source_message_id=msg.id,
    )
    assert prepared.trace.error is None
    assert prepared.case_context["tasks"][-1]["status"] == "blocked"
    assert prepared.results[0].text == doc["text"]
    assert prepared.trace.router_raw_response == raw
    read.assert_awaited_once()
    agent.llm.chat.completions.create.assert_awaited_once()
