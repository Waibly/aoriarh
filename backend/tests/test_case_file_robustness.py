"""Dossier rules that keep answers flowing and facts unambiguous."""
# ruff: noqa: F811 — shared pytest fixture import.

import json
import uuid

from sqlalchemy import select

from app.models.case_file import CaseEntry, CaseFile
from app.models.conversation import Conversation
from app.models.user import User
from app.services.case_file_service import CaseFileService
from app.services.conversation_orchestrator import CaseDelta, enforce_case_entry_rules
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory
from tests.test_case_files import _create_org_and_conversation
from tests.test_chat_document_journey import journey  # noqa: F401
from tests.test_document_extraction_service import dossier  # noqa: F401
from tests.test_dossiers import new_dossier


def proposal(operation="add", target=None, key="salaire", value="2600", **extra):
    return {
        "operation": operation,
        "target_entry_id": target,
        "entry_type": "fact",
        "key": key,
        "label": "Salaire brut",
        "value_text": value,
        "valid_from": None,
        "valid_to": None,
        "source_kind": "user_message",
        "source_excerpt": None,
        "source_document_id": None,
        "source_extraction_id": None,
        **extra,
    }


def test_planner_never_replaces_a_user_controlled_dossier_entry():
    confirmed = str(uuid.uuid4())
    planner_fact = str(uuid.uuid4())
    context = {
        "dossier": {"name": "Licenciement"},
        "entries": [
            {"id": confirmed, "key": "salaire", "status": "confirmed", "source_kind": "user"},
            {"id": planner_fact, "key": "poste", "status": "active", "source_kind": "user_message"},
        ],
    }
    delta = CaseDelta.model_validate_json(
        json.dumps(
            {
                "entries": [
                    proposal("revise", confirmed),
                    proposal("archive", confirmed, key=None, value=None),
                    proposal("revise", planner_fact, key="poste", value="Cadre"),
                    proposal("contest", planner_fact, key="poste", value="Employé"),
                ]
            }
        )
    )
    adjusted, adjustments = enforce_case_entry_rules(delta, context)
    first, second = adjusted.entries
    # The user's confirmed value stays; the new statement becomes a divergence to verify.
    assert (first.operation, first.target_entry_id, first.key) == ("add", None, "salaire")
    assert second.operation == "revise" and str(second.target_entry_id) == planner_fact
    assert [item["error"] for item in adjustments] == [
        "case_entry_requires_user_confirmation",
        "duplicate_case_entry_target",
        "duplicate_case_entry_target",
    ]


def test_private_conversation_case_keeps_planner_revisions():
    confirmed = str(uuid.uuid4())
    context = {"entries": [{"id": confirmed, "key": "salaire", "status": "confirmed"}]}
    delta = CaseDelta.model_validate_json(json.dumps({"entries": [proposal("revise", confirmed)]}))
    adjusted, adjustments = enforce_case_entry_rules(delta, context)
    assert adjusted.entries[0].operation == "revise"
    assert adjustments == []


async def _conversation_case(client, manager_user):
    _, conversation_id = await _create_org_and_conversation(client, manager_user)
    return uuid.UUID(conversation_id)


async def _apply(db, case_file, entries):
    return await CaseFileService(db).apply_planner_delta(
        case_file=case_file,
        expected_version=case_file.version,
        case_delta={"entries": entries},
        case_tasks=[],
        documents=[],
        source_message_id=None,
        user_id=None,
        observation_event_id=uuid.uuid4(),
    )


async def test_second_value_for_a_key_becomes_a_divergence_resolved_by_the_user(
    client, manager_user
):
    conversation_id = await _conversation_case(client, manager_user)
    async with session_factory() as db:
        case_file = (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == conversation_id))
        ).scalar_one()
        await _apply(
            db, case_file, [proposal(value="2500", numeric_value={"number": "2500", "unit": "EUR"})]
        )
        await db.refresh(case_file)
        # Repeating the same fact changes nothing; a different value is not a 2nd active one.
        await _apply(db, case_file, [proposal(value="2500")])
        await db.refresh(case_file)
        await _apply(db, case_file, [proposal(value="2700")])
        entries = list(
            (
                await db.execute(
                    select(CaseEntry)
                    .where(CaseEntry.case_file_id == case_file.id)
                    .order_by(CaseEntry.created_at)
                )
            ).scalars()
        )
        assert [(e.value_text, e.status, e.key) for e in entries] == [
            ("2500", "active", "salaire"),
            ("2700", "contested", None),
        ]
        original, divergent = entries
        assert divergent.value_json["contradicts_entry_ids"] == [str(original.id)]
        version = (await db.get(CaseFile, case_file.id)).version

    headers = auth_header(manager_user["token"])
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/case-file/entries/{divergent.id}/revisions",
        headers=headers,
        json={"operation": "confirm", "expected_case_version": version},
    )
    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in response.json()["entries"]}
    assert by_id[str(original.id)]["status"] == "superseded"
    assert by_id[str(divergent.id)]["status"] == "confirmed"
    assert by_id[str(divergent.id)]["key"] == "salaire"


async def test_correcting_a_numeric_fact_keeps_it_usable_by_calculations(client, manager_user):
    conversation_id = await _conversation_case(client, manager_user)
    async with session_factory() as db:
        case_file = (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == conversation_id))
        ).scalar_one()
        await _apply(db, case_file, [proposal(numeric_value={"number": "2500", "unit": "EUR"})])
        entry = (
            await db.execute(select(CaseEntry).where(CaseEntry.case_file_id == case_file.id))
        ).scalar_one()
        version = (await db.get(CaseFile, case_file.id)).version
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/case-file/entries/{entry.id}/revisions",
        headers=auth_header(manager_user["token"]),
        json={"operation": "correct", "value": "2 600,50 €", "expected_case_version": version},
    )
    assert response.status_code == 200, response.text
    current = next(e for e in response.json()["entries"] if e["status"] == "confirmed")
    assert current["value_json"] == {"number": "2600.50", "unit": "EUR"}


async def test_staff_can_consult_but_not_change_a_personal_dossier(
    client, manager_user, admin_user
):
    org, conversation_id = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    staff = auth_header(admin_user["token"])
    assert (await client.get(f"/api/v1/dossiers/{d['id']}", headers=staff)).status_code == 200
    blocked = [
        await client.post(
            f"/api/v1/dossiers/{d['id']}/entries",
            headers=staff,
            json={"label": "Note", "value": "x", "expected_case_version": 1},
        ),
        await client.patch(
            f"/api/v1/dossiers/{d['id']}", headers=staff, json={"expected_version": 1, "name": "x"}
        ),
        await client.delete(f"/api/v1/dossiers/{d['id']}?expected_version=1", headers=staff),
    ]
    assert [r.status_code for r in blocked] == [404, 404, 404]

    # Same rule for the dossier of an ordinary conversation.
    async with session_factory() as db:
        owner = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        conversation = await db.get(Conversation, uuid.UUID(conversation_id))
        assert conversation.user_id == owner.id
        case_file = (
            await db.execute(
                select(CaseFile).where(CaseFile.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalar_one()
        await _apply(db, case_file, [proposal()])
        entry = (
            await db.execute(select(CaseEntry).where(CaseEntry.case_file_id == case_file.id))
        ).scalar_one()
        version = (await db.get(CaseFile, case_file.id)).version
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/case-file/entries/{entry.id}/revisions",
        headers=staff,
        json={"operation": "archive", "expected_case_version": version},
    )
    assert response.status_code == 404


async def test_failed_dossier_write_still_streams_the_answer_with_a_warning(
    journey, dossier, client, monkeypatch
):
    """End to end: rollback inside preparation must not break the rest of the stream."""
    from unittest.mock import AsyncMock

    from app.services.case_file_service import CaseFileApplyError
    from tests.test_conversation_documents import planner
    from tests.test_conversation_requests import fact, request, wire

    agent = planner(wire([request()], [fact()]))

    async def generate(query, results, **kwargs):
        yield "Réponse conservée"

    agent.stream_generate = generate
    monkeypatch.setattr("app.api.conversations.RAGAgent", lambda: agent)
    monkeypatch.setattr(
        CaseFileService,
        "apply_planner_delta",
        AsyncMock(side_effect=CaseFileApplyError("case_version_conflict")),
    )
    response = await client.post(journey.url + "/chat/stream", json={"message": "Mon salaire"})
    assert response.status_code == 200, response.text
    assert "chat_done" in response.text, response.text
    assert "Réponse conservée" in response.text
    assert "n’ont pas pu être enregistrées dans le dossier" in response.text
    assert "case_execution_conflict" not in response.text
