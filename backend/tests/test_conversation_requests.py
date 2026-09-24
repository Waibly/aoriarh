"""Technical v2 contracts: no editorial assertions or live calls."""

# ruff: noqa: F811
import json

from sqlalchemy import select

from app.models.case_file import CaseEntry, CaseEvent
from app.models.conversation import Message
from app.rag.agent import RagTrace
from app.services.conversation_orchestrator import plan_conversation, prepare_conversation_context
from app.services.conversation_requests import decode_requests, request_schema
from tests.test_conversation_documents import conversation, task_payload
from tests.test_conversation_orchestrator import planner
from tests.test_document_extraction_service import dossier as dossier


def request(kind="answer", id="email", **kwargs):
    kind = {
        "find": "find_existing_document",
        "read": "read_existing_document",
        "passages": "search_uploaded_passages",
    }.get(kind, kind)
    item = dict(
        id=id,
        kind=kind,
        question="Demande complète",
        depends_on=[],
        fact_keys=[],
        replaces_task_id=None,
    )
    item.update({"task_type": "drafting"} if kind == "answer" else {})
    item.update({"use_organisation_convention": True} if kind == "legal" else {})
    return {**item, **kwargs}


def fact():
    return dict(
        operation="add",
        target_entry_id=None,
        entry_type="fact",
        key="salary",
        label="Salaire",
        value_text="3 200 €",
        valid_from=None,
        valid_to=None,
        source_kind="user_message",
        source_excerpt="3 200 €",
        source_document_id=None,
        source_extraction_id=None,
        numeric_value={"number": "3200", "unit": "EUR"},
    )


def wire(requests, entries=None):
    return json.dumps({"case_delta": {"entries": entries or []}, "requests": requests})


def test_contract_has_no_terminal_actions_or_continuation_decision():
    schema = request_schema(3)
    assert set(schema["properties"]) == {"case_delta", "requests"}
    assert "OrchestratorAction" not in schema["$defs"]
    plan, _, _, errors = decode_requests(
        wire(
            [
                request("legal", "law", search=task_payload("documents_and_law")["legal_search"]),
                request(depends_on=["law"]),
            ]
        ),
        previous=[],
        query="Question + mail",
        continuation=False,
    )
    assert not errors
    assert [a.action for a in plan.actions] == ["search_legal"]
    assert len(plan.case_tasks) == 2
    assert not plan.needs_continuation


def test_question_is_declared_once_and_compiled_without_losing_circumstances():
    schema = request_schema(3)
    search_schema = schema["$defs"]["RequestLegalSearch"]
    assert "standalone_question" not in search_schema["properties"]
    assert set(search_schema["required"]) == set(search_schema["properties"])
    search = task_payload("documents_and_law")["legal_search"]
    search.pop("standalone_question")
    question = "Prime de 8 000 € en juin 2026, mission du 1er avril au 30 juin ; CCN inconnue."
    raw = wire([request("legal", "law", question=question, search=search)])
    plan, delta, _, errors = decode_requests(raw, previous=[], query=question, continuation=False)
    assert not errors
    assert delta.entries == []
    assert plan.actions[0].legal_search.standalone_question == question
    assert plan.case_tasks[0].question == question


def test_partial_date_is_not_repaired_and_does_not_block_independent_request():
    raw = wire([request()], [{**fact(), "valid_from": "2026-06"}])
    plan, delta, _, errors = decode_requests(raw, previous=[], query="Q", continuation=False)
    assert delta is None
    assert errors[0]["error"] == "invalid_case_delta"
    assert plan.case_tasks[0].id == "email"


def test_continuation_cannot_restart_document_discovery():
    schema = request_schema(3, continuation=True)
    choices = schema["properties"]["requests"]["items"]["anyOf"]
    assert {"$ref": "#/$defs/FindRequest"} not in choices
    plan, _, _, errors = decode_requests(
        wire([request("read", "read_again", source_request_id=None), request()]),
        previous=[],
        query="Q",
        continuation=True,
    )
    assert plan.actions == []
    assert [t.id for t in plan.case_tasks] == ["email"]
    assert errors[0]["error"] == "document_discovery_already_completed"


def test_unknown_convention_is_not_used_as_a_search_filter():
    from app.rag.search_plan import SourceRequirement, build_deterministic_search_plan
    from app.services.conversation_orchestrator import PlannedConversation, legal_plan

    raw = wire(
        [
            request(
                "legal",
                "law",
                use_organisation_convention=False,
                search=task_payload("documents_and_law")["legal_search"],
            )
        ]
    )
    plan, delta, requests, _ = decode_requests(raw, previous=[], query="Q", continuation=False)
    base = build_deterministic_search_plan("Q", org_idcc_list=["1486"])
    compiled = legal_plan(
        PlannedConversation(plan, base, RagTrace(), raw, delta, requests), plan.actions[0]
    )
    assert compiled.applicable_idccs == []
    assert compiled.ccn == SourceRequirement.DISABLED


def test_independent_invalid_operation_does_not_discard_facts_or_other_requests():
    plan, delta, _, errors = decode_requests(
        wire(
            [
                request("read", "invalid", source_request_id="unknown"),
                request(),
            ],
            [fact()],
        ),
        previous=[],
        query="Q",
        continuation=False,
    )
    assert delta.entries[0].value_text == "3 200 €"
    assert [t.id for t in plan.case_tasks] == ["email"]
    assert errors[0]["error"] == "invalid_request_dependency"


def test_unauthorized_fact_source_is_not_applied_but_request_remains():
    entry = {
        **fact(),
        "source_kind": "document",
        "source_document_id": "00000000-0000-0000-0000-000000000001",
        "source_extraction_id": "00000000-0000-0000-0000-000000000002",
    }
    plan, delta, _, errors = decode_requests(
        wire([request()], [entry]), previous=[], query="Q", continuation=False
    )
    assert delta is None
    assert not plan.case_delta.entries
    assert errors[0]["error"] == "unknown_case_document_source"


def test_continuation_preserves_requests_without_regeneration():
    first, _, prior, _ = decode_requests(
        wire(
            [
                request("legal", "law", search=task_payload("documents_and_law")["legal_search"]),
                request("calculation", "calc", specification=None, depends_on=["law"]),
            ]
        ),
        previous=[],
        query="Q",
        continuation=False,
    )
    assert first.needs_continuation
    second, _, _, errors = decode_requests(
        wire([request(depends_on=["law"])]), previous=prior, query="Q", continuation=True
    )
    assert not errors
    assert not second.actions
    assert [t.id for t in second.case_tasks] == ["law", "calc", "email"]
    assert not second.needs_continuation


async def test_live_contract_uses_one_call_and_preserves_raw():
    raw = wire([request()])
    agent = planner(raw)
    result = await plan_conversation(
        agent,
        query="Un mail",
        history=[],
        active_documents=[],
        documents=[],
        tool_results=[],
        continuation=False,
        model="test",
        request_contract=True,
    )
    assert result.plan is not None
    assert result.raw == raw
    assert agent.llm.chat.completions.create.await_count == 1
    sent = agent.llm.chat.completions.create.await_args.kwargs
    assert set(sent["response_format"]["json_schema"]["schema"]["properties"]) == {
        "case_delta",
        "requests",
    }


async def test_default_pipeline_persists_facts_even_when_search_fails(dossier):
    conv, _ = await conversation(dossier)
    msg = Message(
        conversation_id=conv.id, role="user", content="Salaire 3 200 € ; question et mail"
    )
    dossier.db.add(msg)
    await dossier.db.commit()
    raw = wire(
        [
            request("legal", "law", search=task_payload("documents_and_law")["legal_search"]),
            request(),
        ],
        [fact()],
    )

    async def failed_search(*args, **kwargs):
        # Facts are saved before any external search starts.
        assert (await dossier.db.execute(select(CaseEntry))).scalars().one().value_text == "3 200 €"
        raise RuntimeError("transport")

    result = await prepare_conversation_context(
        planner(raw),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query=msg.content,
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=failed_search,
        model="test",
        source_message_id=msg.id,
    )
    assert result.generate_without_sources
    assert result.case_context["tasks"][0]["status"] == "blocked"
    assert result.case_context["tasks"][0]["answer_intent"] == (
        task_payload("documents_and_law")["legal_search"]["answer_intent"]
    )
    assert result.case_context["tasks"][1]["status"] == "ready_for_generation"
    events = (
        (
            await dossier.db.execute(
                select(CaseEvent).where(CaseEvent.event_type == "planner_observation")
            )
        )
        .scalars()
        .all()
    )
    assert events[0].raw_planner_output == raw


async def test_independent_legal_requests_are_parallel_with_drafting(dossier):
    import asyncio

    conv, _ = await conversation(dossier)
    message = Message(conversation_id=conv.id, role="user", content="Comparer, puis procédure et mail")
    dossier.db.add(message)
    await dossier.db.commit()
    entered = []
    both = asyncio.Event()

    async def search(query, **kwargs):
        entered.append(query)
        if len(entered) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 1)
        return [], query, RagTrace(query_original=query)

    raw = wire(
        [
            request("legal", "law1", search={
                **task_payload("documents_and_law")["legal_search"], "answer_intent": "comparison",
            }),
            request("legal", "law2", search={
                **task_payload("documents_and_law")["legal_search"], "answer_intent": "procedure",
            }),
            request(),
        ]
    )
    result = await prepare_conversation_context(
        planner(raw),
        db=dossier.db,
        conversation=conv,
        user=dossier.user,
        query="Q",
        references=[],
        documents=[],
        document_continuity="",
        history=[],
        legal_search=search,
        model="test",
        parallel_legal_search=True,
        source_message_id=message.id,
    )
    assert len(entered) == 2
    intents = {task["id"]: task.get("answer_intent") for task in result.case_context["tasks"]}
    assert intents == {"law1": "comparison", "law2": "procedure", "email": None}
