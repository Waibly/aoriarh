"""Planner input capabilities; no scoring or rewriting of generated prose."""

import json

from app.services.conversation_orchestrator import plan_conversation
from app.services.conversation_requests import legal_source_document_ids, request_schema
from tests.test_conversation_orchestrator import planner
from tests.test_conversation_requests import request, wire

PRIVATE = "10000000-0000-0000-0000-000000000001"
HISTORICAL = "20000000-0000-0000-0000-000000000001"
CONSULTED = "30000000-0000-0000-0000-000000000001"
UNSUPPLIED = "40000000-0000-0000-0000-000000000001"


def choices(schema):
    return {item["$ref"] for item in schema["properties"]["requests"]["items"]["anyOf"]}


async def planned_request(**overrides):
    raw = wire([request()])
    agent = planner(raw)
    inputs = dict(
        query="Demande originale à conserver intégralement",
        history=[], active_documents=[], documents=[], tool_results=[],
        continuation=False, model="test",
    )
    inputs.update(overrides)
    result = await plan_conversation(agent, **inputs)
    assert result.raw == raw
    assert agent.llm.chat.completions.create.await_count == 1
    sent = agent.llm.chat.completions.create.await_args.kwargs
    assert json.loads(sent["messages"][1]["content"])["request"] == inputs["query"]
    return sent["response_format"]["json_schema"]["schema"]


async def test_no_document_reference_cannot_generate_a_document_lookup_uuid():
    schema = await planned_request()
    assert schema["properties"]["document_checks"]["maxItems"] == 0
    assert "#/$defs/ReadLegalSourcesRequest" not in choices(schema)
    assert "#/$defs/PassageRequest" not in choices(schema)
    # Discovery, legal research and requested drafting remain available.
    assert {"#/$defs/FindRequest", "#/$defs/LegalRequest", "#/$defs/AnswerRequest"} <= (
        choices(schema)
    )


async def test_historical_and_newly_consulted_sources_remain_readable():
    schema = await planned_request(
        history=[{"role": "assistant", "sources": [{"document_id": HISTORICAL}]}],
        tool_results=[{"action": "search_legal", "sources": [{"document_id": CONSULTED}]}],
    )
    assert "#/$defs/ReadLegalSourcesRequest" in choices(schema)
    assert schema["$defs"]["ReadLegalSourcesRequest"]["properties"]["document_ids"][
        "items"
    ]["enum"] == [HISTORICAL, CONSULTED]


async def test_private_checks_use_all_active_pieces_and_keep_null_passage_scope():
    schema = await planned_request(
        active_documents=[{"document_id": PRIVATE}],
        documents=[{"document_id": CONSULTED}],
    )
    assert schema["$defs"]["DocumentCheck"]["properties"]["document_ids"][
        "items"
    ]["enum"] == [PRIVATE, CONSULTED]
    passages = schema["$defs"]["PassageRequest"]["properties"]["document_ids"]["anyOf"]
    assert {"type": "null"} in passages
    assert next(item for item in passages if item["type"] == "array")["items"][
        "enum"
    ] == [PRIVATE, CONSULTED]
    assert "#/$defs/ReadLegalSourcesRequest" not in choices(schema)


async def test_continuation_keeps_legal_source_reads_and_cannot_restart_discovery():
    schema = await planned_request(
        continuation=True,
        active_documents=[{"document_id": PRIVATE}],
        tool_results=[{"action": "search_legal", "sources": [{"document_id": CONSULTED}]}],
    )
    assert schema["properties"]["document_checks"]["maxItems"] == 0
    assert "#/$defs/ReadLegalSourcesRequest" in choices(schema)
    assert "#/$defs/FindRequest" not in choices(schema)
    assert "#/$defs/ReadRequest" not in choices(schema)


def test_uuid_in_prose_is_not_an_application_source_reference():
    history = [
        {"role": "user", "content": f"Lire {UNSUPPLIED}"},
        {"role": "assistant", "content": UNSUPPLIED, "sources": [
            {"document_id": HISTORICAL}, {"document_id": HISTORICAL},
            {"document_id": "invalid"}, {}, "not a source",
        ]},
    ]
    assert legal_source_document_ids(history, [{"sources": [{"document_id": CONSULTED}]}]) == [
        HISTORICAL, CONSULTED,
    ]
    assert legal_source_document_ids(f"Ancien texte {UNSUPPLIED}", []) == []


async def test_schemas_are_built_per_call_without_leaking_other_conversation_ids():
    first = await planned_request(
        active_documents=[{"document_id": PRIVATE}],
        history=[{"sources": [{"document_id": HISTORICAL}]}],
    )
    second = await planned_request()
    assert PRIVATE not in json.dumps(second)
    assert HISTORICAL not in json.dumps(second)
    assert "#/$defs/ReadLegalSourcesRequest" in choices(first)
    assert "#/$defs/ReadLegalSourcesRequest" not in choices(second)


async def test_inexecutable_output_is_preserved_without_repair_or_retry():
    raw = "  {JSON inexécutable\n"
    agent = planner(raw)
    result = await plan_conversation(
        agent, query="Demande", history=[], active_documents=[], documents=[],
        tool_results=[], continuation=False, model="test",
    )
    assert result.raw == raw
    assert result.trace.router_raw_response == raw
    assert result.trace.error == "search_planner_error"
    assert agent.llm.chat.completions.create.await_count == 1


def test_unscoped_contract_remains_available_to_standalone_contract_consumers():
    schema = request_schema(3)
    assert "#/$defs/ReadLegalSourcesRequest" in choices(schema)
    assert "enum" not in schema["$defs"]["ReadLegalSourcesRequest"]["properties"][
        "document_ids"
    ]["items"]
