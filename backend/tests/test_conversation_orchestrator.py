"""Bounded orchestration contracts. No paid call and no editorial evaluator."""
# ruff: noqa: F811 -- shared pytest fixture is intentionally injected by name.

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models.case_file import CaseDocumentLink, CaseEntry, CaseEvent, CaseFile, CaseTask
from app.models.conversation import Message
from app.models.document import Document
from app.models.membership import Membership
from app.rag.agent import RAGAgent, RagTrace
from app.rag.search import SearchResult
from app.services.case_file_service import CaseFileApplyError, CaseFileService
from app.services.conversation_orchestrator import (
    ConversationPlan,
    plan_conversation,
    prepare_conversation_context,
)
from tests.test_conversation_documents import conversation, task_payload
from tests.test_document_extraction_service import dossier as dossier


def request_payload(payload, **options):
    """Build current request-wire fixtures from the executor operations under test."""
    requests = list(payload.get("requests", []))
    tasks = payload.get("case_tasks", [])
    if tasks:
        requests = [r for r in requests if r["kind"] != "answer"]
    for operation in payload.get("actions", []):
        kind = operation["action"]
        if tasks and kind in {"generate", "respond"}:
            continue
        item = {
            "id": operation["id"],
            "question": operation.get("query") or "Demande complète",
            "depends_on": operation.get("depends_on", []),
            "fact_keys": [],
            "replaces_task_id": None,
        }
        if kind == "search_legal":
            item.update(
                kind="legal", search=operation["legal_search"], use_organisation_convention=True
            )
        elif kind == "find_documents":
            item.update(kind="find_existing_document", lookup=operation["lookup"])
        elif kind == "read_documents":
            item.update(
                kind="read_existing_document", source_request_id=operation.get("source_action_id")
            )
        elif kind == "search_documents":
            item.update(kind="search_uploaded_passages")
        else:
            item.update(
                kind="answer", task_type="clarification" if kind == "respond" else "drafting"
            )
            item["question"] = operation.get("response") or item["question"]
        requests.append(item)
    for task in tasks:
        item = {
            "id": task["id"],
            "question": task["question"],
            "depends_on": task.get("depends_on", []),
            "fact_keys": task.get("relevant_entry_keys", []),
            "replaces_task_id": task.get("replaces_task_id"),
        }
        if task["task_type"] == "calculation":
            item.update(kind="calculation", specification=task.get("calculation"))
        else:
            item.update(kind="answer", task_type=task["task_type"])
        requests.append(item)
    return json.dumps(
        {"case_delta": payload.get("case_delta", {"entries": []}), "requests": requests}, **options
    )


def action(kind, action_id, *, depends_on=None, **values):
    payload = {
        "id": action_id,
        "action": kind,
        "depends_on": depends_on or [],
        "lookup": None,
        "source": None,
        "source_action_id": None,
        "query": None,
        "legal_search": None,
        "response": None,
    }
    payload.update(values)
    return payload


def plan(actions, *, continuation=False):
    return request_payload(
        {
            "objective": "Traiter la demande originale",
            "actions": actions,
            "needs_continuation": continuation,
            "case_delta": {"entries": []},
            "case_tasks": [],
        }
    )


def planner(*raw_outputs):
    responses = [
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw, refusal=None))],
            usage=None,
        )
        for raw in raw_outputs
    ]
    llm = MagicMock()
    llm.with_options.return_value = llm
    llm.chat.completions.create = AsyncMock(side_effect=responses)
    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = llm
    return agent


async def test_final_generation_receives_exact_case_context_and_keeps_raw_output():
    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = MagicMock()

    async def chunks():
        yield SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(delta=SimpleNamespace(content="  Réponse intégrale\n"))],
        )

    agent.llm.chat.completions.create = AsyncMock(return_value=chunks())
    context = {
        "dossier": {"version": 5, "entries": [{"value_text": "3 200 €"}]},
        "tasks": [{"question": "Calculer", "status": "blocked"}],
    }
    previous_mail = "Détail conservé. " * 200 + "Pièce importante en fin de courrier."
    output = "".join(
        [
            part
            async for part in agent.stream_generate(
                "Ma demande originale",
                [],
                case_context=context,
                answer_format="main_risk_then_secondary_risks",
                history=[{"role": "assistant", "content": previous_mail}],
            )
        ]
    )
    assert output == "  Réponse intégrale\n"
    sent = agent.llm.chat.completions.create.await_args.kwargs["messages"]
    actual = sent[1]["content"].split("DOSSIER ET RÉSULTATS PAR TÂCHE:\n", 1)[1]
    assert json.loads(actual) == context
    assert "Ma demande originale" in sent[1]["content"]
    assert "Format de réponse déterminé par le plan" not in sent[1]["content"]
    assert previous_mail in sent[1]["content"]


async def test_first_fragment_is_yielded_immediately_without_changing_text():
    agent = RAGAgent.__new__(RAGAgent)
    agent.llm = MagicMock()
    consumed = []

    async def chunks():
        for text in ["  Début", "\n", "suite  "]:
            consumed.append(text)
            yield SimpleNamespace(
                usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
            )

    agent.llm.chat.completions.create = AsyncMock(return_value=chunks())
    metrics = {}
    stream = agent.stream_generate("Question", [], generation_metrics=metrics)
    first = await anext(stream)
    assert first == "  Début"
    assert consumed == ["  Début"]
    assert first + "".join([part async for part in stream]) == "  Début\nsuite  "
    assert metrics["user_chars"] > 0


@pytest.mark.parametrize("parallel", [False, True])
async def test_distinct_legal_branches_keep_passages_from_same_document(dossier, parallel):
    conv, _ = await conversation(dossier)
    message = Message(conversation_id=conv.id, role="user", content="Deux questions")
    dossier.db.add(message)
    await dossier.db.commit()
    actions = [
        action(
            "search_legal",
            f"law_{i}",
            query=f"Question {i}",
            legal_search=task_payload("documents_and_law")["legal_search"],
        )
        for i in range(2)
    ]
    legal = AsyncMock(
        side_effect=[
            (
                [
                    SearchResult(
                        text=f"Article {i}",
                        doc_name="Code",
                        document_id="same-code",
                        source_type="code_travail",
                        norme_niveau=1,
                        norme_poids=1,
                        chunk_index=i,
                        score=1,
                    )
                ],
                f"Question {i}",
                RagTrace(),
            )
            for i in range(2)
        ]
    )
    started = []
    all_started = asyncio.Event()

    async def concurrent_search(*args, **kwargs):
        started.append(args[0])
        if len(started) == 2:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        return await legal(*args, **kwargs)

    prepared = await prepare_conversation_context(
        planner(plan(actions)),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=message.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=concurrent_search if parallel else legal,
        parallel_legal_search=parallel,
        model="test",
        source_message_id=message.id,
    )
    assert len(prepared.results) == 2
    assert [branch["question"] for branch in prepared.case_context["branches"]] == [
        "Question 0",
        "Question 1",
    ]
    # Original request is supplied by generation already, not duplicated in dossier.
    assert "original_request" not in prepared.case_context


@pytest.mark.parametrize("document_after", [False, True])
async def test_successful_branch_survives_failure_or_later_document_read(dossier, document_after):
    conv, refs = await conversation(dossier)
    message = Message(conversation_id=conv.id, role="user", content="Deux opérations")
    dossier.db.add(message)
    await dossier.db.commit()
    law = SearchResult(
        text="Règle conservée",
        doc_name="Code",
        document_id="code",
        source_type="code_travail",
        norme_niveau=1,
        norme_poids=1,
        chunk_index=0,
        score=1,
    )
    actions = [
        action(
            "search_legal",
            "law",
            query="Question une",
            legal_search=task_payload("documents_and_law")["legal_search"],
        )
    ]
    docs = []
    if document_after:
        actions.append(action("read_documents", "read", source="active"))
        docs = [{**refs[0], "text": "Pièce", "source_name": "Pièce", "coverage": {}}]
    else:
        actions.append(
            action(
                "search_legal",
                "failure",
                query="Question deux",
                legal_search=task_payload("documents_and_law")["legal_search"],
            )
        )
    prepared = await prepare_conversation_context(
        planner(plan(actions)),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=message.content,
        references=refs if document_after else [],
        documents=docs,
        document_continuity="",
        history=[],
        model="test",
        source_message_id=message.id,
        legal_search=AsyncMock(side_effect=[([law], "Question une", RagTrace()), RuntimeError()]),
    )
    assert prepared.trace.error is None
    assert any(result.text == "Règle conservée" for result in prepared.results)
    if not document_after:
        assert prepared.case_context["branches"][1]["status"] == "search_retrieval_error"


async def test_open_task_is_explicitly_replaced_and_answer_is_audited(dossier):
    conv, _ = await conversation(dossier)
    service = CaseFileService(dossier.db)
    case_file, _ = await service.observation_context(conv)
    previous = CaseTask(
        case_file_id=case_file.id,
        task_type="clarification",
        question="Quel salaire ?",
        status="blocked",
    )
    message = Message(conversation_id=conv.id, role="user", content="3200 euros")
    dossier.db.add_all([previous, message])
    await dossier.db.commit()
    payload = json.loads(plan([action("respond", "ask", response="Quelle ancienneté ?")]))
    payload["case_tasks"] = [
        {
            "id": "clarify",
            "task_type": "clarification",
            "question": "Quelle ancienneté ?",
            "depends_on": [],
            "relevant_entry_keys": [],
            "required_document_ids": [],
            "action_ids": ["ask"],
            "replaces_task_id": str(previous.id),
        }
    ]
    await prepare_conversation_context(
        planner(request_payload(payload)),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=message.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        model="test",
        source_message_id=message.id,
        legal_search=AsyncMock(),
    )
    await dossier.db.refresh(previous)
    assert previous.status == "superseded"
    answer = Message(conversation_id=conv.id, role="assistant", content="Quelle ancienneté ?")
    dossier.db.add(answer)
    await dossier.db.commit()
    ids = (conv.id, message.id, answer.id)
    with pytest.raises(CaseFileApplyError, match="case_version_conflict"):
        await service.link_task_answer(*ids, expected_version=0)
    unfinished = (
        await dossier.db.execute(select(CaseTask).where(CaseTask.created_from_message_id == ids[1]))
    ).scalar_one()
    assert unfinished.result_message_id is None
    assert unfinished.status == "ready_for_generation"
    assert await service.link_task_answer(*ids) is not None
    event = (
        await dossier.db.execute(select(CaseEvent).where(CaseEvent.event_type == "tasks_finalized"))
    ).scalar_one()
    assert event.structured_delta["answer_id"] == str(ids[2])


async def test_context_budget_is_explicit_and_does_not_call_or_truncate_llm():
    agent = planner()
    result = await plan_conversation(
        agent,
        query="x" * 250_001,
        history=[],
        active_documents=[],
        documents=[],
        tool_results=[],
        continuation=False,
        model="test",
    )
    assert result.plan is None
    assert result.trace.error == "case_context_budget_exceeded"
    assert result.trace.query_original == "x" * 250_001
    agent.llm.chat.completions.create.assert_not_called()


@pytest.mark.parametrize(
    "failed_stage",
    [
        "record_planner_observation",
        "apply_planner_delta",
        "record_task_execution",
    ],
)
async def test_dossier_write_failure_returns_explicit_error_after_rollback(
    dossier, monkeypatch, failed_stage
):
    conv, _ = await conversation(dossier)
    message = Message(conversation_id=conv.id, role="user", content="Préciser")
    dossier.db.add(message)
    await dossier.db.commit()
    payload = json.loads(plan([action("respond", "ask", response="Quelle date ?")]))
    payload["case_tasks"] = [
        {
            "id": "clarify",
            "task_type": "clarification",
            "question": "Quelle date ?",
            "depends_on": [],
            "relevant_entry_keys": [],
            "required_document_ids": [],
            "action_ids": ["ask"],
        }
    ]
    monkeypatch.setattr(
        CaseFileService,
        failed_stage,
        AsyncMock(side_effect=CaseFileApplyError("case_version_conflict")),
    )
    prepared = await prepare_conversation_context(
        planner(request_payload(payload)),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=message.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
        source_message_id=message.id,
    )
    assert prepared.trace.error == "case_execution_conflict"
    assert prepared.trace.router_raw_response == request_payload(payload)


@pytest.mark.parametrize("proposed_value", ["3200.10", "9999"])
async def test_calculation_is_stored_and_invalidated_after_fact_correction(dossier, proposed_value):
    conv, _ = await conversation(dossier)
    message = Message(
        conversation_id=conv.id, role="user", content="Multiplier mon salaire par trois"
    )
    dossier.db.add(message)
    service = CaseFileService(dossier.db)
    case_file, _ = await service.observation_context(conv)
    entry = CaseEntry(
        case_file_id=case_file.id,
        entry_type="fact",
        key="salary",
        label="Salaire",
        value_text="3200.10",
        source_kind="user_message",
    )
    dossier.db.add(entry)
    await dossier.db.commit()
    payload = json.loads(plan([action("generate", "answer")]))
    payload["case_tasks"] = [
        {
            "id": "salary_three_months",
            "task_type": "calculation",
            "question": "Trois mois",
            "depends_on": [],
            "relevant_entry_keys": ["salary"],
            "required_document_ids": [],
            "action_ids": [],
            "calculation": {
                "expression": "salary * 3",
                "variables": [
                    {
                        "name": "salary",
                        "value": proposed_value,
                        "unit": "EUR",
                        "entry_key": "salary",
                    }
                ],
                "source_document_ids": [],
                "formula_source": "Demande utilisateur : multiplier par trois",
                "assumptions": ["Simulation sans qualification juridique"],
                "scenario": "Trois mois",
                "unit": "EUR",
            },
        }
    ]
    prepared = await prepare_conversation_context(
        planner(request_payload(payload)),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=message.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
        source_message_id=message.id,
    )
    if proposed_value == "9999":
        result = prepared.case_context["tasks"][0]
        assert result["status"] == "technical_error"
        assert result["error"] == "calculation_fact_value_mismatch"
        assert result["specification"]["variables"][0]["value"] == "9999"
        return
    assert prepared.case_context["tasks"][0]["result"] == "9600.30"
    calculation = (
        await dossier.db.execute(select(CaseEntry).where(CaseEntry.entry_type == "calculation"))
    ).scalar_one()
    assert calculation.value_json["relevant_entry_ids"] == [str(entry.id)]
    await service.apply_user_entry_action(
        conversation_id=conv.id,
        entry_id=entry.id,
        expected_version=case_file.version,
        user=dossier.user,
        operation="correct",
        value_text="3300.10",
    )
    await dossier.db.refresh(calculation)
    assert calculation.status == "stale"
    assert calculation.value_text == "9600.30"


def test_plan_accepts_ordered_multiple_actions_and_rejects_duplicate_ids():
    valid = {
        "objective": "Lire le dernier dépôt",
        "actions": [
            action(
                "find_documents",
                "find_latest",
                lookup={
                    "name": None,
                    "uploaded_from": None,
                    "uploaded_to": None,
                    "uploader": "current_user",
                    "order": "newest",
                    "limit": 1,
                },
            ),
            action(
                "read_documents",
                "read_latest",
                depends_on=["find_latest"],
                source="find_result",
                source_action_id="find_latest",
            ),
        ],
        "needs_continuation": True,
        "case_delta": {"entries": []},
        "case_tasks": [],
    }
    assert len(ConversationPlan.model_validate(valid).actions) == 2
    valid["actions"][1]["id"] = "find_latest"
    with pytest.raises(ValueError, match="duplicate_action_id"):
        ConversationPlan.model_validate(valid)


async def test_invalid_raw_plan_is_visible_and_never_retried():
    agent = planner("sortie brute non JSON")
    result = await plan_conversation(
        agent,
        query="q",
        history=[],
        active_documents=[],
        documents=[],
        tool_results=[],
        continuation=False,
        model="test",
    )
    assert result.plan is None
    assert result.trace.error == "search_planner_error"
    assert result.trace.router_raw_response == "sortie brute non JSON"
    assert agent.llm.chat.completions.create.await_count == 1


async def test_case_observation_rejects_unknown_document_identifiers_without_retry():
    raw = request_payload(
        {
            "objective": "Observer une pièce",
            "actions": [action("generate", "generate_answer")],
            "needs_continuation": False,
            "case_delta": {
                "entries": [
                    {
                        "operation": "add",
                        "target_entry_id": None,
                        "entry_type": "fact",
                        "key": "unknown_document_fact",
                        "label": "Fait de pièce",
                        "value_text": "Valeur",
                        "valid_from": None,
                        "valid_to": None,
                        "source_kind": "document",
                        "source_excerpt": "Extrait",
                        "source_document_id": str(uuid.uuid4()),
                        "source_extraction_id": str(uuid.uuid4()),
                    }
                ]
            },
            "case_tasks": [],
        }
    )
    agent = planner(raw)

    result = await plan_conversation(
        agent,
        query="Question",
        history=[],
        active_documents=[],
        documents=[],
        tool_results=[],
        continuation=False,
        model="test",
    )

    assert result.plan is not None  # Independent answer remains executable.
    assert result.fact_delta is None
    assert result.raw == raw
    assert result.trace.search_plan_validation["request_errors"] == [
        {"scope": "case_delta", "error": "unknown_case_document_source"}
    ]
    assert agent.llm.chat.completions.create.await_count == 1


async def test_case_observation_preserves_complex_facts_and_tasks_without_applying_them(
    dossier,
):
    conv, _ = await conversation(dossier)
    raw = request_payload(
        {
            "objective": "Analyser un licenciement économique complexe",
            "actions": [action("generate", "generate_answer")],
            "needs_continuation": False,
            "case_delta": {
                "entries": [
                    {
                        "operation": "add",
                        "target_entry_id": None,
                        "entry_type": "fact",
                        "key": "exceptional_bonus",
                        "label": "Prime exceptionnelle versée en juin 2026",
                        "value_text": "8 000 €",
                        "valid_from": "2026-06-01",
                        "valid_to": "2026-06-30",
                        "source_kind": "user_message",
                        "source_excerpt": "prime exceptionnelle de 8 000 € versée en juin 2026",
                        "source_document_id": None,
                        "source_extraction_id": None,
                    },
                    {
                        "operation": "add",
                        "target_entry_id": None,
                        "entry_type": "fact",
                        "key": "dismissal_letter_received_at",
                        "label": "Réception du recommandé",
                        "value_text": "2 juillet 2026",
                        "valid_from": "2026-07-02",
                        "valid_to": None,
                        "source_kind": "user_message",
                        "source_excerpt": "date de réception du recommandé : le 2 juillet 2026",
                        "source_document_id": None,
                        "source_extraction_id": None,
                    },
                ]
            },
            "case_tasks": [
                {
                    "id": "determine_salary_base",
                    "task_type": "calculation",
                    "question": "Comparer les bases sur trois et douze mois.",
                    "depends_on": [],
                    "relevant_entry_keys": ["exceptional_bonus"],
                    "required_document_ids": [],
                },
                {
                    "id": "determine_notification_date",
                    "task_type": "legal_question",
                    "question": "Déterminer la date juridique de notification.",
                    "depends_on": [],
                    "relevant_entry_keys": ["dismissal_letter_received_at"],
                    "required_document_ids": [],
                },
            ],
        },
        ensure_ascii=False,
    )

    result = await prepare_conversation_context(
        planner(raw),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Expose complet du licenciement",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
        org_context={"nom": "Société test", "taille": "20-49"},
    )

    assert result.generate_without_sources is True
    assert result.trace.case_file_observation["mode"] == "observation"
    assert len(result.trace.case_file_observation["event_ids"]) == 1
    case_file = (
        await dossier.db.execute(select(CaseFile).where(CaseFile.conversation_id == conv.id))
    ).scalar_one()
    event = (
        await dossier.db.execute(
            select(CaseEvent).where(CaseEvent.event_type == "planner_observation")
        )
    ).scalar_one()
    assert event.raw_planner_output == raw
    assert event.case_version == 1
    assert event.structured_delta["case_delta"]["entries"][0]["value_text"] == "8 000 €"
    assert len(event.structured_delta["case_tasks"]) == 2
    assert event.organisation_context_snapshot["taille"] == "20-49"
    assert case_file.version == 1
    assert (await dossier.db.execute(select(CaseEntry))).scalars().all() == []
    assert (await dossier.db.execute(select(CaseTask))).scalars().all() == []


async def test_valid_case_delta_is_applied_once_with_message_provenance(dossier):
    conv, _ = await conversation(dossier)
    source_message = Message(
        conversation_id=conv.id,
        role="user",
        content="Prime de 8 000 € et calcul de mes indemnités",
    )
    dossier.db.add(source_message)
    await dossier.db.commit()
    raw = request_payload(
        {
            "objective": "Calculer les indemnités",
            "actions": [action("generate", "generate_answer")],
            "needs_continuation": False,
            "case_delta": {
                "entries": [
                    {
                        "operation": "add",
                        "target_entry_id": None,
                        "entry_type": "fact",
                        "key": "exceptional_bonus",
                        "label": "Prime exceptionnelle",
                        "value_text": "8 000 €",
                        "valid_from": "2026-06-01",
                        "valid_to": "2026-06-30",
                        "source_kind": "user_message",
                        "source_excerpt": "Prime de 8 000 €",
                        "source_document_id": None,
                        "source_extraction_id": None,
                    }
                ]
            },
            "case_tasks": [
                {
                    "id": "calculate_indemnities",
                    "task_type": "calculation",
                    "question": "Calculer les indemnités.",
                    "depends_on": [],
                    "relevant_entry_keys": ["exceptional_bonus"],
                    "required_document_ids": [],
                },
                {
                    "id": "draft_summary",
                    "task_type": "drafting",
                    "question": "Rédiger une synthèse du calcul.",
                    "depends_on": ["calculate_indemnities"],
                    "relevant_entry_keys": ["exceptional_bonus"],
                    "required_document_ids": [],
                },
            ],
        }
    )

    result = await prepare_conversation_context(
        planner(raw),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=source_message.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
        source_message_id=source_message.id,
    )

    case_file = (
        await dossier.db.execute(select(CaseFile).where(CaseFile.conversation_id == conv.id))
    ).scalar_one()
    entry = (await dossier.db.execute(select(CaseEntry))).scalar_one()
    tasks = (
        (await dossier.db.execute(select(CaseTask).order_by(CaseTask.created_at))).scalars().all()
    )
    await dossier.db.refresh(case_file)
    assert case_file.version == 4
    assert entry.value_text == "8 000 €"
    assert entry.source_message_id == source_message.id
    assert all(task.created_from_message_id == source_message.id for task in tasks)
    assert all(task.relevant_entry_ids == [str(entry.id)] for task in tasks)
    assert tasks[0].depends_on == []
    assert tasks[1].depends_on == [str(tasks[0].id)]
    assert result.trace.case_file_observation["mode"] == "applied"
    application_result = result.trace.case_file_observation["application_result"]
    assert application_result["applied"] is True
    assert application_result["version"] == 4
    assert application_result["entries_created"] == 0  # Facts persisted before execution.
    assert application_result["tasks_created"] == 2
    events = (await dossier.db.execute(select(CaseEvent))).scalars().all()
    assert [event.event_type for event in events] == [
        "created",
        "planner_observation",
        "delta_applied",
        "delta_applied",
        "tasks_executed",
    ]


async def test_planner_delta_keeps_revision_contestation_and_archive_history(dossier):
    conv, _ = await conversation(dossier)
    source_message = Message(
        conversation_id=conv.id,
        role="user",
        content="Mon salaire était 3 000 €, puis 3 200 € ; le montant reste contesté.",
    )
    dossier.db.add(source_message)
    await dossier.db.commit()

    service = CaseFileService(dossier.db)
    case_file, _ = await service.observation_context(conv)
    case_file_id = case_file.id

    async def observation(version: int) -> CaseEvent:
        event = await service.record_planner_observation(
            case_file=case_file,
            raw_planner_output=f"observation version {version}",
            structured_delta={"case_delta": {"entries": []}, "case_tasks": []},
            technical_error=None,
            organisation_context_snapshot=None,
            source_message_id=source_message.id,
        )
        return event

    def proposal(operation: str, value: str | None, target_id: uuid.UUID | None = None):
        return {
            "operation": operation,
            "target_entry_id": str(target_id) if target_id else None,
            "entry_type": "fact",
            "key": "monthly_salary",
            "label": "Salaire mensuel",
            "value_text": value,
            "valid_from": None,
            "valid_to": None,
            "source_kind": "user_message",
            "source_excerpt": value,
            "source_document_id": None,
            "source_extraction_id": None,
        }

    first_event = await observation(1)
    first_result = await service.apply_planner_delta(
        case_file=case_file,
        expected_version=1,
        case_delta={"entries": [proposal("add", "3 000 €")]},
        case_tasks=[],
        documents=[],
        source_message_id=source_message.id,
        user_id=dossier.user.id,
        observation_event_id=first_event.id,
    )
    original_id = uuid.UUID(first_result["created_entry_ids"][0])

    second_event = await observation(2)
    second_result = await service.apply_planner_delta(
        case_file=case_file,
        expected_version=2,
        case_delta={"entries": [proposal("revise", "3 200 €", original_id)]},
        case_tasks=[],
        documents=[],
        source_message_id=source_message.id,
        user_id=dossier.user.id,
        observation_event_id=second_event.id,
    )
    replacement_id = uuid.UUID(second_result["created_entry_ids"][0])

    third_event = await observation(3)
    third_result = await service.apply_planner_delta(
        case_file=case_file,
        expected_version=3,
        case_delta={"entries": [proposal("contest", "Montant à confirmer", replacement_id)]},
        case_tasks=[],
        documents=[],
        source_message_id=source_message.id,
        user_id=dossier.user.id,
        observation_event_id=third_event.id,
    )
    contested_id = uuid.UUID(third_result["created_entry_ids"][0])

    fourth_event = await observation(4)
    await service.apply_planner_delta(
        case_file=case_file,
        expected_version=4,
        case_delta={"entries": [proposal("archive", None, contested_id)]},
        case_tasks=[],
        documents=[],
        source_message_id=source_message.id,
        user_id=dossier.user.id,
        observation_event_id=fourth_event.id,
    )

    entries = {
        entry.id: entry for entry in (await dossier.db.execute(select(CaseEntry))).scalars().all()
    }
    assert entries[original_id].status == "superseded"
    assert entries[replacement_id].status == "contested"
    assert entries[replacement_id].supersedes_entry_id == original_id
    assert entries[contested_id].status == "archived"
    assert len(entries) == 3
    assert (await dossier.db.get(CaseFile, case_file_id)).version == 5

    stale_event = await observation(5)
    with pytest.raises(CaseFileApplyError, match="case_version_conflict"):
        await service.apply_planner_delta(
            case_file=case_file,
            expected_version=4,
            case_delta={"entries": [proposal("add", "3 300 €")]},
            case_tasks=[],
            documents=[],
            source_message_id=source_message.id,
            user_id=dossier.user.id,
            observation_event_id=stale_event.id,
        )
    await dossier.db.rollback()
    assert (await dossier.db.get(CaseFile, case_file_id)).version == 5
    assert len((await dossier.db.execute(select(CaseEntry))).scalars().all()) == 3


async def test_invalid_case_observation_is_stored_raw_without_repair(dossier):
    conv, _ = await conversation(dossier)
    agent = planner("sortie brute invalide à conserver")

    result = await prepare_conversation_context(
        agent,
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Question",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
    )

    event = (
        await dossier.db.execute(
            select(CaseEvent).where(CaseEvent.event_type == "planner_observation")
        )
    ).scalar_one()
    assert event.raw_planner_output == "sortie brute invalide à conserver"
    assert event.structured_delta is None
    assert event.technical_error == "invalid_planner_output"
    assert result.trace.error == "search_planner_error"
    assert agent.llm.chat.completions.create.await_count == 1


async def test_planner_transport_error_is_recorded_once_and_propagated(dossier):
    conv, _ = await conversation(dossier)
    agent = planner("unused")
    agent.llm.chat.completions.create = AsyncMock(side_effect=TimeoutError("timeout"))

    with pytest.raises(TimeoutError, match="timeout"):
        await prepare_conversation_context(
            agent,
            db=dossier.db,
            conversation=conv,
            user=dossier.user,
            query="Question",
            references=[],
            documents=[],
            document_continuity="",
            history=[],
            legal_search=AsyncMock(),
            model="test",
        )

    event = (
        await dossier.db.execute(
            select(CaseEvent).where(CaseEvent.event_type == "planner_observation")
        )
    ).scalar_one()
    assert event.raw_planner_output is None
    assert event.technical_error == "planner_transport_error"
    assert agent.llm.chat.completions.create.await_count == 1
    options = agent.llm.with_options.call_args.kwargs
    assert options["max_retries"] == 0
    assert options["timeout"].read == 300.0


async def test_latest_document_is_found_read_and_reused_by_continuation(dossier, monkeypatch):
    conv, _ = await conversation(dossier)
    source_message = Message(
        conversation_id=conv.id,
        role="user",
        content="Résume le dernier document que j'ai ajouté",
    )
    dossier.db.add(source_message)
    dossier.doc.uploaded_by = dossier.user.id
    await dossier.db.commit()
    monkeypatch.setattr(
        "app.services.document_extraction_service.StorageService",
        lambda: dossier.storage,
    )
    first = plan(
        [
            action(
                "find_documents",
                "find_latest",
                lookup={
                    "name": None,
                    "uploaded_from": None,
                    "uploaded_to": None,
                    "uploader": "current_user",
                    "order": "newest",
                    "limit": 1,
                },
            ),
            action(
                "read_documents",
                "read_latest",
                depends_on=["find_latest"],
                source="find_result",
                source_action_id="find_latest",
            ),
        ],
        continuation=True,
    )
    second = plan(
        [
            action(
                "search_documents",
                "inspect_document",
                source="active",
                source_action_id=None,
                query="Résume le document",
            )
        ]
    )
    agent = planner(first, second)
    legal = AsyncMock()

    result = await prepare_conversation_context(
        agent,
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Résume le dernier document que j'ai ajouté",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=legal,
        model="test",
        source_message_id=source_message.id,
    )

    assert [reference["document_id"] for reference in result.references] == [str(dossier.doc.id)]
    assert result.results[0].text.startswith("  Pièce originale")
    assert result.trace.search_plan_usage["planner_calls"] == 2
    assert result.trace.error is None
    assert [item["status"] for item in result.trace.search_plan["tool_results"][:2]] == [
        "unique",
        "success",
    ]
    legal.assert_not_awaited()
    link = (await dossier.db.execute(select(CaseDocumentLink))).scalar_one()
    assert link.document_id == dossier.doc.id
    assert link.added_from_message_id == source_message.id


async def test_ambiguous_filename_is_never_silently_selected(dossier):
    conv, _ = await conversation(dossier)
    dossier.doc.name = "Entretien annuel.txt"
    dossier.doc.uploaded_by = dossier.user.id
    dossier.db.add(
        Document(
            organisation_id=dossier.org.id,
            name="Entretien annuel.pdf",
            source_type="divers",
            storage_path="second/entretien.pdf",
            uploaded_by=dossier.user.id,
        )
    )
    await dossier.db.commit()
    first = plan(
        [
            action(
                "find_documents",
                "find_interview",
                lookup={
                    "name": "Entretien annuel",
                    "uploaded_from": None,
                    "uploaded_to": None,
                    "uploader": "current_user",
                    "order": "newest",
                    "limit": 1,
                },
            ),
            action(
                "read_documents",
                "read_interview",
                depends_on=["find_interview"],
                source="find_result",
                source_action_id="find_interview",
            ),
        ],
        continuation=True,
    )
    second = plan(
        [
            action(
                "respond",
                "ask_choice",
                response=(
                    "J’ai trouvé deux documents nommés Entretien annuel. "
                    "Lequel souhaitez-vous consulter ?"
                ),
            )
        ]
    )

    result = await prepare_conversation_context(
        planner(first, second),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Lis Entretien annuel",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=AsyncMock(),
        model="test",
    )

    assert result.references == []
    assert result.results == []
    assert result.generate_without_sources is True
    assert result.trace.search_plan_usage["planner_calls"] == 1
    assert result.trace.search_plan["tool_results"][0]["status"] == "ambiguous"


async def test_pure_legal_question_uses_one_planner_call_and_existing_legal_executor(dossier):
    conv, _ = await conversation(dossier)
    raw = plan(
        [
            action(
                "search_legal",
                "search_law",
                query="Quelle est la durée légale ?",
                legal_search=task_payload("documents_and_law")["legal_search"],
            )
        ]
    )
    agent = planner(raw)
    legal_result = SearchResult(
        text="Article de test",
        doc_name="Code du travail",
        document_id="law",
        source_type="code_travail",
        norme_niveau=1,
        norme_poids=1,
        chunk_index=0,
        score=1,
    )
    legal = AsyncMock(return_value=([legal_result], "question autonome", RagTrace()))

    result = await prepare_conversation_context(
        agent,
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Quelle est la durée légale ?",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=legal,
        model="test",
    )

    assert result.results == [legal_result]
    assert result.reformulated == "question autonome"
    assert agent.llm.chat.completions.create.await_count == 1
    assert legal.await_count == 1
    assert legal.await_args.kwargs["search_plan"].query_original == "Quelle est la durée légale ?"


async def test_natural_lookup_rechecks_membership_before_exposing_catalogue(dossier):
    conv, _ = await conversation(dossier)
    await dossier.db.execute(delete(Membership).where(Membership.user_id == dossier.user.id))
    await dossier.db.commit()
    raw = plan(
        [
            action(
                "find_documents",
                "find_file",
                lookup={
                    "name": "confidentiel",
                    "uploaded_from": None,
                    "uploaded_to": None,
                    "uploader": "organisation",
                    "order": "newest",
                    "limit": 5,
                },
            )
        ]
    )

    with pytest.raises(HTTPException) as exc:
        await prepare_conversation_context(
            planner(raw),
            db=dossier.db,
            conversation=conv,
            user=dossier.user,
            query="Trouve confidentiel",
            references=[],
            documents=[],
            document_continuity="",
            history=[],
            legal_search=AsyncMock(),
            model="test",
        )

    assert exc.value.status_code == 404


async def test_actions_based_on_new_document_content_wait_for_continuation(dossier, monkeypatch):
    conv, _ = await conversation(dossier)
    dossier.doc.uploaded_by = dossier.user.id
    await dossier.db.commit()
    monkeypatch.setattr(
        "app.services.document_extraction_service.StorageService",
        lambda: dossier.storage,
    )
    lookup = {
        "name": None,
        "uploaded_from": None,
        "uploaded_to": None,
        "uploader": "current_user",
        "order": "newest",
        "limit": 1,
    }
    legal_payload = task_payload("documents_and_law")["legal_search"]
    first = plan(
        [
            action("find_documents", "find_latest", lookup=lookup),
            action(
                "read_documents",
                "read_latest",
                depends_on=["find_latest"],
                source="find_result",
                source_action_id="find_latest",
            ),
            action(
                "search_legal",
                "premature_law",
                depends_on=["read_latest"],
                source="read_result",
                source_action_id="read_latest",
                legal_search=legal_payload,
            ),
        ],
        continuation=True,
    )
    second = plan(
        [
            action(
                "search_legal",
                "informed_law",
                legal_search=legal_payload,
            )
        ]
    )
    legal_result = SearchResult(
        text="Règle après lecture",
        doc_name="Code du travail",
        document_id="law",
        source_type="code_travail",
        norme_niveau=1,
        norme_poids=1,
        chunk_index=0,
        score=1,
    )
    legal = AsyncMock(return_value=([legal_result], "question", RagTrace()))

    result = await prepare_conversation_context(
        planner(first, second),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Prends mon dernier document et vérifie mes droits",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=legal,
        model="test",
    )

    assert legal.await_count == 1
    statuses = [item["status"] for item in result.trace.search_plan["tool_results"]]
    assert "deferred_to_continuation" in statuses
    assert result.trace.error is None
