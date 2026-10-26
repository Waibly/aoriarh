"""Storage compatibility of planner JSON; never an editorial answer validator."""

import json

import pytest

from app.services.conversation_orchestrator import plan_conversation
from app.services.conversation_requests import decode_requests
from tests.test_conversation_documents import task_payload
from tests.test_conversation_orchestrator import planner
from tests.test_conversation_requests import fact, request, wire


def payload():
    return json.loads(wire([
        request("legal", "law", search=task_payload("documents_and_law")["legal_search"]),
        request(depends_on=["law"]),
    ], [fact()]))


@pytest.mark.parametrize("location", ["question", "fact", "unit", "key", "theme", "missing"])
async def test_decoded_nul_blocks_plan_before_any_facts_can_be_applied(location):
    value = payload()
    if location == "question":
        value["requests"][1]["question"] = "Texte\x00original"
    elif location == "fact":
        value["case_delta"]["entries"][0]["value_text"] = "Salaire\x00déclaré"
    elif location == "unit":
        value["case_delta"]["entries"][0]["numeric_value"]["unit"] = "EUR\x00/month"
    elif location == "key":
        value["case_delta"]["entries"][0]["numeric_value"] = {"unit\x00": "EUR"}
    elif location == "theme":
        value["requests"][0]["search"]["legal_topics"] = ["salari\x00e9"]
    else:
        value["requests"][0]["search"]["missing_facts"] = ["Texte\x00original"]
    raw = "  " + json.dumps(value, ensure_ascii=False) + "\n"
    assert "\x00" not in raw
    agent = planner(raw)
    result = await plan_conversation(
        agent, query="Demande", history=[], active_documents=[], documents=[],
        tool_results=[], continuation=False, model="test",
    )
    assert result.plan is None
    assert result.fact_delta is None
    assert result.requests is None
    assert result.raw == raw
    assert result.trace.router_raw_response == raw
    assert result.trace.error == "search_planner_error"
    assert result.trace.search_plan_validation["technical_error"] == "planner_json_contains_nul"
    agent.llm.chat.completions.create.assert_awaited_once()


@pytest.mark.parametrize("text", [
    "  Salarié : 3 200 €\n\t原文 😀  ",
    r"Écrire littéralement \u0000, sans interpréter cet exemple.",
    "Texte avec séparateur\u2028et null comme mot",
])
def test_valid_unicode_and_literal_escape_text_are_preserved(text):
    raw = wire([request(question=text)])
    plan, _, requests, errors = decode_requests(
        raw, previous=[], query="Question", continuation=False,
    )
    assert not errors
    assert plan.case_tasks[0].question == text
    assert requests[0]["question"] == text


def test_json_null_is_allowed_and_is_not_a_nul_character():
    plan, delta, requests, errors = decode_requests(
        wire([request()]), previous=[], query="Question", continuation=False,
    )
    assert not errors
    assert requests[0]["replaces_task_id"] is None
    assert delta.entries == []
    assert len(plan.case_tasks) == 1


def test_discarded_invalid_value_does_not_block_independent_valid_request_or_fact():
    raw = wire([
        request("read", "invalid", source_request_id={"invalid_value": "\x00"}),
        request(),
    ], [fact()])
    plan, delta, requests, errors = decode_requests(
        raw, previous=[], query="Question", continuation=False,
    )
    assert errors[0]["error"] == "invalid_request"
    assert [item["id"] for item in requests] == ["email"]
    assert [task.id for task in plan.case_tasks] == ["email"]
    assert delta.entries[0].value_text == "3 200 €"
