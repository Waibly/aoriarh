"""Technical isolation checks for the opt-in pilot, not answer quality validators."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.experiments import dossier_evidence_probe as base
from scripts.experiments.dossier_evidence_followup import EvidenceCapture


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [False, True])
async def test_hidden_fixture_passage_only_reaches_generation_after_requested_consultation(
    monkeypatch, requested
):
    case = base.fixtures()[0]
    sent = []
    record = dict(_fixture=case, tool_results=[], calls=[])

    async def fake_create(self, **kwargs):
        sent.append(kwargs)
        record["calls"].append({})
        if kwargs.get("stream"):
            return "stream"
        actions = (
            [dict(kind="search_uploaded_passages", question="Condition pour taxi tardif ?")]
            if requested
            else []
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=json.dumps(dict(actions=actions))))
            ]
        )

    monkeypatch.setattr(base.Capture, "create", fake_create)
    capture = EvidenceCapture(None, record, "C", {}, None)
    await capture.create(stream=True, messages=[dict(role="user", content="Original context")])
    evidence_input = sent[0]["messages"][1]["content"]
    assert "65 euros" not in evidence_input
    final = sent[-1]["messages"][0]["content"]
    assert ("65 euros" in final) is requested


@pytest.mark.asyncio
async def test_complete_documents_do_not_trigger_extra_call(monkeypatch):
    case = base.fixtures()[1]
    send = AsyncMock(return_value="stream")
    monkeypatch.setattr(base.Capture, "create", send)
    capture = EvidenceCapture(None, dict(_fixture=case, tool_results=[], calls=[]), "C", {}, None)
    await capture.create(stream=True, messages=[])
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_ambiguous_catalogue_cannot_supply_either_private_document(monkeypatch):
    case = base.fixtures()[5]
    sent = AsyncMock(return_value="stream")
    monkeypatch.setattr(base.Capture, "create", sent)
    capture = EvidenceCapture(
        None,
        dict(
            _fixture=case,
            tool_results=[dict(action="find_documents", status="ambiguous")],
            calls=[],
        ),
        "C",
        {},
        None,
    )
    await capture.create(stream=True, messages=[])
    assert sent.await_count == 1
    assert "Martin Dupont prend" not in str(sent.call_args)
    assert "Martin Legrand prend" not in str(sent.call_args)
