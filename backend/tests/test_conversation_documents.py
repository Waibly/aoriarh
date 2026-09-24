"""Documentary chat slice: real HTTP/DB/extraction, no paid calls."""
# ruff: noqa: F811 — pytest imports the shared fixture, then injects it by name.

import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.models.conversation import Conversation, Message
from app.rag.agent import RAGAgent, RagTrace
from app.rag.search import SearchResult
from app.schemas.conversation import ChatDocumentReference
from app.services.conversation_document_service import (
    active_references,
    prepare_document_task,
    read_conversation_documents,
)
from app.services.document_extraction_service import SourceSnapshot
from app.rag.text_extractor import TextExtractor
from tests.test_chat_stream_timeouts import _passthrough_intent
from tests.test_document_extraction_service import dossier as dossier
from tests.test_document_extraction_service import prepare


def planner(raw):
    llm = MagicMock()
    llm.with_options.return_value = llm
    llm.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw, refusal=None))],
            usage=None,
        )
    )
    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = llm
    return agent


def task_payload(action="documents_and_law"):
    return dict(action=action, objective="Répondre à la demande", legal_search=(dict(
        needs_history=True, standalone_question="Question et faits du document inchangés",
        legal_topics=["durée"], search_queries=["durée essai cadre CDI"],
        hypothesized_articles=[], source_hints=["legislation"],
        jurisprudence="optional", answer_intent="case_analysis", missing_facts=[],
    ) if action == "documents_and_law" else None))


def orchestration_payload(action="documents_and_law"):
    actions = [{
        "id": "read_active",
        "action": "read_documents",
        "depends_on": [],
        "lookup": None,
        "source": "active",
        "source_action_id": None,
        "query": None,
        "legal_search": None,
        "response": None,
    }]
    if action == "documents_and_law":
        actions.append({
            "id": "search_law",
            "action": "search_legal",
            "depends_on": ["read_active"],
            "lookup": None,
            "source": None,
            "source_action_id": None,
            "query": None,
            "legal_search": task_payload(action)["legal_search"],
            "response": None,
        })
    return {
        "objective": "Répondre à la demande",
        "actions": actions,
        "needs_continuation": False,
        "case_delta": {"entries": []},
        "case_tasks": [],
    }


async def conversation(dossier):
    value = Conversation(
        id=uuid.uuid4(),
        organisation_id=dossier.org.id,
        user_id=dossier.user.id,
        messages=[],
        title="Document test",
    )
    dossier.db.add(value)
    await dossier.db.commit()
    manifest = await prepare(dossier)
    refs = [{"document_id": str(dossier.doc.id), "extraction_id": str(manifest["extraction_id"])}]
    return value, refs


def test_references_inherit_replace_and_clear_without_semantic_matching():
    ref = {"document_id": str(uuid.uuid4()), "extraction_id": str(uuid.uuid4())}
    history = [SimpleNamespace(role="user", document_references=[ref])]
    history += [SimpleNamespace(role="assistant", document_references=None)] * 20
    assert active_references(history, None) == [ref]
    assert active_references(history, []) == []
    new = ChatDocumentReference(document_id=uuid.uuid4(), extraction_id=uuid.uuid4())
    assert active_references(history, [new]) == [new.model_dump(mode="json")]


async def test_full_history_and_original_extraction_are_read(dossier, monkeypatch):
    conv, refs = await conversation(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    conv.messages = [Message(role="user", content="Original " + "x" * 2100 + " FIN_ORIGINALE")]
    conv.messages += [Message(role="assistant", content="Intermédiaire") for _ in range(8)]
    docs, continuity = await read_conversation_documents(
        dossier.db, conv, dossier.user, refs, reader=dossier.service
    )
    assert docs[0]["text"].startswith("  Pièce originale")
    assert "FIN_ORIGINALE" in continuity
    assert continuity.count("Intermédiaire") == 8


async def test_long_document_uses_only_passages_from_the_explicit_document(
    dossier, monkeypatch
):
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    conv = Conversation(
        id=uuid.uuid4(), organisation_id=dossier.org.id, user_id=dossier.user.id,
        messages=[], title="Long document",
    )
    dossier.db.add(conv)
    long_text = "Introduction\n" + ("contenu administratif\n" * 6000) + "Montant : 2 750 euros"
    raw = long_text.encode()
    dossier.doc.storage_path = f"{dossier.org.id}/long.txt"
    dossier.doc.file_hash = hashlib.sha256(raw).hexdigest()
    dossier.doc.indexation_status = "indexed"
    dossier.storage.objects[dossier.doc.storage_path] = raw
    await dossier.db.commit()
    await dossier.service.extract(SourceSnapshot.from_document(dossier.doc), raw, TextExtractor())
    manifest = await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)
    refs = [{"document_id": str(dossier.doc.id),
             "extraction_id": str(manifest["extraction_id"])}]
    searcher = SimpleNamespace(search=AsyncMock(return_value=[SearchResult(
        text="Montant : 2 750 euros", doc_name=dossier.doc.name,
        document_id=str(dossier.doc.id), source_type="divers", norme_niveau=9,
        norme_poids=.1, chunk_index=42, score=1,
    )]))

    documents, _ = await read_conversation_documents(
        dossier.db, conv, dossier.user, refs, query="Quel est le montant ?",
        reader=dossier.service, searcher=searcher,
    )

    assert documents[0]["text"] == "Montant : 2 750 euros"
    assert documents[0]["transmitted_scope"] == "targeted_passages"
    assert documents[0]["selected_chunk_indices"] == [42]
    assert searcher.search.await_args.kwargs["document_ids"] == [str(dossier.doc.id)]


async def test_long_document_waits_for_index_without_fallback_read(dossier, monkeypatch):
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    conv = Conversation(
        id=uuid.uuid4(), organisation_id=dossier.org.id, user_id=dossier.user.id,
        messages=[], title="Long document pending",
    )
    dossier.db.add(conv)
    raw = ("texte\n" * 20_000).encode()
    dossier.doc.storage_path = f"{dossier.org.id}/long-pending.txt"
    dossier.doc.file_hash = hashlib.sha256(raw).hexdigest()
    dossier.doc.indexation_status = "pending"
    dossier.storage.objects[dossier.doc.storage_path] = raw
    await dossier.db.commit()
    await dossier.service.extract(SourceSnapshot.from_document(dossier.doc), raw, TextExtractor())
    manifest = await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)
    refs = [{"document_id": str(dossier.doc.id),
             "extraction_id": str(manifest["extraction_id"])}]

    with pytest.raises(HTTPException, match="encore en préparation") as exc:
        await read_conversation_documents(
            dossier.db, conv, dossier.user, refs, query="Résume", reader=dossier.service,
        )
    assert exc.value.status_code == 409


@pytest.mark.parametrize("case", ["disabled", "duplicate", "long_history", "replacement"])
async def test_invalid_document_context_is_refused_not_repaired(dossier, monkeypatch, case):
    conv, refs = await conversation(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", case != "disabled")
    if case == "duplicate":
        refs *= 2
    if case == "long_history":
        conv.messages = [Message(role="user", content="x" * 144000)]
    if case == "replacement":
        dossier.doc.storage_path = "new-source"
        await dossier.db.commit()
    with pytest.raises(HTTPException):
        await read_conversation_documents(
            dossier.db, conv, dossier.user, refs, reader=dossier.service
        )


@pytest.mark.parametrize("action", ["documents", "documents_and_law"])
async def test_action_runs_exactly_the_requested_capability(dossier, monkeypatch, action):
    conv, refs = await conversation(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    docs, continuity = await read_conversation_documents(
        dossier.db, conv, dossier.user, refs, reader=dossier.service
    )
    raw = json.dumps(task_payload(action))
    agent = planner(raw)
    legal = AsyncMock(return_value=([], "query", RagTrace()))
    results, _, trace = await prepare_document_task(
        agent,
        query="Ma demande exacte",
        documents=docs,
        continuity=continuity,
        legal_search=legal,
        model="test",
    )
    assert legal.await_count == (action == "documents_and_law")
    assert trace.router_raw_response == raw
    assert results[0].text == docs[0]["text"]
    if action == "documents_and_law":
        assert trace.error == "search_context_error"  # Missing legal evidence is not hidden.
        args, kwargs = legal.await_args
        assert args == ("Ma demande exacte",)
        assert kwargs["search_plan"].planner_status.value == "ok"
        assert kwargs["search_plan"].planner_raw_response == raw


@pytest.mark.parametrize("raw", ["  sortie originale non JSON\n", '{"action":"delete_files"}', ""])
async def test_invalid_plan_is_kept_and_never_retried(raw):
    agent = planner(raw)
    legal = AsyncMock()
    results, _, trace = await prepare_document_task(
        agent, query="q", documents=[], continuity="", legal_search=legal, model="test"
    )
    assert trace.error == "search_planner_error"
    assert trace.router_raw_response == (raw or None)
    assert results == [] and agent.llm.chat.completions.create.await_count == 1
    legal.assert_not_awaited()


async def test_legal_transport_error_keeps_the_original_decision():
    raw = json.dumps(task_payload())
    agent = planner(raw)
    _, _, trace = await prepare_document_task(
        agent,
        query="q",
        documents=[],
        continuity="",
        legal_search=AsyncMock(side_effect=RuntimeError("offline")),
        model="test",
    )
    assert trace.router_raw_response == raw
    assert trace.error == "search_retrieval_error"


async def test_unified_plan_reaches_real_executor_without_second_planner(monkeypatch):
    from app.rag import agent as agent_module
    from app.rag.pipeline import prepare_rag_context

    raw = json.dumps(task_payload())
    agent = planner(raw)
    second_planner = AsyncMock(side_effect=AssertionError("No second planning call"))
    monkeypatch.setattr(agent_module, "run_compact_search_planner", second_planner)
    # Stop at retrieval, after the real pipeline's planning branch.
    agent._search_with_plan = AsyncMock(side_effect=RuntimeError("retrieval boundary"))

    async def legal(query, *, search_plan):
        return await prepare_rag_context(
            agent, query=query, organisation_id="org-fixture", search_plan=search_plan,
        )

    _, _, trace = await prepare_document_task(
        agent, query="  Et mon document ?  ", documents=[], continuity="historique intégral",
        legal_search=legal, model="test", org_idcc_list=["1486"],
        org_context={"not_subject_to_ccn": True},
    )
    second_planner.assert_not_awaited()
    assert agent.llm.chat.completions.create.await_count == 1
    call = agent.llm.chat.completions.create.await_args.kwargs
    schema = call["response_format"]["json_schema"]["schema"]
    constraints = json.loads(call["messages"][1]["content"])["search_context"]["constraints"]
    assert schema["$defs"]["DocumentLegalSearch"]["properties"]["search_queries"]["maxItems"] == (
        constraints["query_budget"]
    )
    plan = agent._search_with_plan.await_args.args[0]
    assert plan.query_original == "  Et mon document ?  "
    assert plan.applicable_idccs == []
    assert plan.ccn.value == "disabled"
    assert plan.standalone_question == task_payload()["legal_search"]["standalone_question"]
    assert trace.error == "search_retrieval_error"
    assert trace.router_raw_response == raw


@pytest.mark.parametrize("fault", ["missing_arguments", "unexpected_arguments", "budget", "tenant"])
async def test_unexecutable_unified_plan_stops_without_repair(fault):
    value = task_payload()
    if fault == "missing_arguments":
        value["legal_search"] = None
    elif fault == "unexpected_arguments":
        value["action"] = "documents"
    elif fault == "budget":
        value["legal_search"]["search_queries"] = ["one", "two", "three", "four"]
    else:
        value["legal_search"]["organisation_id"] = "another-tenant"
    raw = json.dumps(value)
    agent, legal = planner(raw), AsyncMock()
    _, _, trace = await prepare_document_task(
        agent, query="question", documents=[], continuity="", legal_search=legal, model="test",
    )
    assert trace.error == "search_planner_error"
    assert trace.router_raw_response == raw
    assert agent.llm.chat.completions.create.await_count == 1
    legal.assert_not_awaited()


def test_message_reference_migration_roundtrip():
    import runpy
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "alembic/versions/g6h7chatdocs01_message_document_references.py"
        )
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)"))
        conn.execute(sa.text("INSERT INTO messages VALUES (1, 'original')"))
        migration["upgrade"].__globals__["op"] = Operations(MigrationContext.configure(conn))
        migration["upgrade"]()
        assert "document_references" in {
            c["name"] for c in sa.inspect(conn).get_columns("messages")
        }
        migration["downgrade"]()
        assert conn.execute(sa.text("SELECT content FROM messages")).scalar_one() == "original"
    engine.dispose()


@pytest.mark.parametrize("action", ["documents", "documents_and_law"])
async def test_http_second_turn_reads_same_documents_and_keeps_raw_answer(
    dossier, client, monkeypatch, action
):
    from app.core.dependencies import get_current_user
    from app.main import app

    conv, refs = await conversation(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    app.dependency_overrides[get_current_user] = lambda: dossier.user
    monkeypatch.setattr(
        "app.services.document_extraction_service.StorageService", lambda: dossier.storage
    )
    monkeypatch.setattr("app.api.conversations.classify_intent", _passthrough_intent)
    from tests.test_conversation_requests import request, wire

    requests = [request("read", "read_active", source_request_id=None)]
    if action == "documents_and_law":
        requests.append(request("legal", "law", depends_on=["read_active"],
                                search=task_payload(action)["legal_search"]))
    raw_plan = wire(requests)
    agent = planner(raw_plan)
    monkeypatch.setattr("app.api.conversations.RAGAgent", lambda: agent)
    async def prepared_legal_context(agent, *, query, search_plan, **kwargs):
        from app.rag.search import SearchResult

        assert search_plan.query_original == query
        assert search_plan.planner_raw_response == raw_plan
        return [SearchResult(text="Texte juridique de test", doc_name="Loi de test",
                             document_id="legal", source_type="code_travail", norme_niveau=1,
                             norme_poids=1, chunk_index=0, score=1)], query, RagTrace(
                                 search_plan=search_plan.to_dict())

    legal = AsyncMock(side_effect=prepared_legal_context)
    monkeypatch.setattr("app.api.conversations.prepare_rag_context", legal)
    monkeypatch.setattr(
        "app.api.conversations.BillingService",
        lambda db: SimpleNamespace(
            get_account_for_organisation=AsyncMock(return_value=SimpleNamespace()),
            check_question_quota=AsyncMock(),
            increment_question_count=AsyncMock(),
        ),
    )
    observed = []

    async def generate(query, results, **kwargs):
        observed.append((query, results, kwargs))
        yield "  réponse brute\n"

    agent.stream_generate = generate
    for body in (
        {"message": "Lis cette pièce", "document_references": refs},
        {"message": "Et le train ?"},
    ):
        response = await client.post(f"/api/v1/conversations/{conv.id}/chat/stream", json=body)
        assert "chat_done" in response.text, response.text
        assert "chat_error" not in response.text, response.text
    assert len(observed) == 2
    assert observed[0][2]["document_task_context"]["action"] == action
    assert observed[0][2]["document_task_context"]["sources"][0]["role"] == "case_document"
    assert legal.await_count == (2 if action == "documents_and_law" else 0)
    if action == "documents_and_law":
        assert observed[0][2]["answer_format"] == "main_risk_then_secondary_risks"
    assert "Lis cette pièce" in observed[1][2]["document_continuity"]
    assert observed[1][1][0].text == observed[0][1][0].text
    messages = (
        (await dossier.db.execute(select(Message).order_by(Message.created_at))).scalars().all()
    )
    assert [m.content for m in messages if m.role == "assistant"] == ["  réponse brute\n"] * 2
    assert all(
        m.document_references[0]["extraction_id"] == refs[0]["extraction_id"]
        for m in messages
        if m.role == "user"
    )


async def test_http_upload_creates_company_document_and_readable_reference(
    dossier, client, monkeypatch
):
    from app.core.dependencies import get_current_user
    from app.main import app
    from app.models.document import Document

    conv, _ = await conversation(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    app.dependency_overrides[get_current_user] = lambda: dossier.user
    monkeypatch.setattr("app.services.document_service.storage", dossier.storage)

    async def upload(file, path):
        dossier.storage.objects[path] = await file.read()

    monkeypatch.setattr(dossier.storage, "upload_file", upload, raising=False)
    monkeypatch.setattr("app.rag.tasks.enqueue_ingestion", AsyncMock())
    monkeypatch.setattr(
        "app.api.conversations.BillingService",
        lambda db: SimpleNamespace(
            get_account_for_organisation=AsyncMock(return_value=SimpleNamespace()),
            ensure_plan_active=MagicMock(),
            check_document_limit=AsyncMock(),
        ),
    )
    response = await client.post(
        f"/api/v1/conversations/{conv.id}/documents",
        files={"file": ("chat.txt", b"Content from the message composer", "text/plain")},
    )
    assert response.status_code == 201, response.text
    ref = response.json()
    doc = await dossier.db.get(Document, uuid.UUID(ref["document_id"]))
    assert doc.organisation_id == dossier.org.id and doc.source_type == "divers"
    text = await dossier.service.read(
        doc.id, dossier.org.id, dossier.user.id, uuid.UUID(ref["extraction_id"]), 24000
    )
    assert text["text"] == "Content from the message composer"


async def test_http_upload_rejects_revoked_member_before_storage(dossier, client, monkeypatch):
    from sqlalchemy import delete

    from app.core.dependencies import get_current_user
    from app.main import app
    from app.models.membership import Membership

    conv, _ = await conversation(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    app.dependency_overrides[get_current_user] = lambda: dossier.user
    await dossier.db.execute(delete(Membership).where(Membership.user_id == dossier.user.id))
    await dossier.db.commit()
    before = dict(dossier.storage.objects)
    response = await client.post(
        f"/api/v1/conversations/{conv.id}/documents",
        files={"file": ("chat.txt", b"No access", "text/plain")},
    )
    assert response.status_code == 403
    assert dossier.storage.objects == before
