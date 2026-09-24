import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.models.case_file import CaseEntry, CaseEvent, CaseFile
from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.user import User
from app.services.case_file_service import (
    CaseFileService,
    delete_case_files_for_conversations,
)
from app.services.data_retention_service import DataRetentionService
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def test_pilot_access_is_scoped_to_configured_organisations(
    client, manager_user, monkeypatch
):
    from app.core.config import settings

    org_id, conversation_id = await _create_org_and_conversation(client, manager_user)
    monkeypatch.setattr(settings, "case_file_enabled", False)
    monkeypatch.setattr(settings, "case_file_pilot_organisation_ids", [])
    path = f"/api/v1/conversations/{conversation_id}/case-file"
    assert (await client.get(path, headers=auth_header(manager_user["token"]))).status_code == 404
    monkeypatch.setattr(settings, "case_file_pilot_organisation_ids", [uuid.UUID(org_id)])
    assert (await client.get(path, headers=auth_header(manager_user["token"]))).status_code == 200


async def test_history_import_preserves_selected_message_and_rejects_foreign_ids(
    client, manager_user
):
    _, conversation_id = await _create_org_and_conversation(client, manager_user)
    async with session_factory() as db:
        message = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="user",
            content="  Ma situation exacte\n8 000 € en juin.  ",
        )
        db.add(message)
        await db.commit()
        message_id = str(message.id)
    path = f"/api/v1/conversations/{conversation_id}/case-file/import-history"
    response = await client.post(
        path,
        headers=auth_header(manager_user["token"]),
        json={
            "message_ids": [message_id],
            "expected_case_version": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["entries"][0]["value_text"] == (
        "  Ma situation exacte\n8 000 € en juin.  "
    )
    repeated = await client.post(
        path,
        headers=auth_header(manager_user["token"]),
        json={
            "message_ids": [message_id],
            "expected_case_version": 2,
        },
    )
    assert repeated.status_code == 200
    assert len(repeated.json()["entries"]) == 1
    refused = await client.post(
        path,
        headers=auth_header(manager_user["token"]),
        json={
            "message_ids": [str(uuid.uuid4())],
            "expected_case_version": 2,
        },
    )
    assert refused.status_code == 404


async def test_raw_events_accessible_without_assistant_answer(client, manager_user):
    _, conversation_id = await _create_org_and_conversation(client, manager_user)
    async with session_factory() as db:
        case_file = (
            await db.execute(
                select(CaseFile).where(CaseFile.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalar_one()
        db.add(
            CaseEvent(
                case_file_id=case_file.id,
                case_version=1,
                event_type="planner_observation",
                actor_type="llm_observer",
                raw_planner_output="  {invalid}\n",
                technical_error="invalid_planner_output",
            )
        )
        await db.commit()
    path = f"/api/v1/conversations/{conversation_id}/case-file/events"
    response = await client.get(path, headers=auth_header(manager_user["token"]))
    assert response.status_code == 200
    assert (
        next(item for item in response.json()["items"] if item["type"] == "planner_observation")[
            "raw_planner_output"
        ]
        == "  {invalid}\n"
    )
    assert (await client.get(path)).status_code == 401


async def _create_org_and_conversation(
    client: AsyncClient, actor: dict[str, str], *, suffix: str = "case"
) -> tuple[str, str]:
    org_response = await client.post(
        "/api/v1/organisations/",
        json={
            "name": f"Société {suffix}",
            "forme_juridique": "SAS",
            "taille": "20-49",
            "secteur_activite": "Conseil",
            "convention_collective": "Convention test",
        },
        headers=auth_header(actor["token"]),
    )
    assert org_response.status_code == 201
    org_id = org_response.json()["id"]
    conversation_response = await client.post(
        "/api/v1/conversations/",
        json={"organisation_id": org_id, "title": "Situation complexe"},
        headers=auth_header(actor["token"]),
    )
    assert conversation_response.status_code == 201
    return org_id, conversation_response.json()["id"]


@pytest.mark.asyncio
async def test_conversation_initialises_case_file_with_inherited_context(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    _, conversation_id = await _create_org_and_conversation(client, manager_user)

    response = await client.get(
        f"/api/v1/conversations/{conversation_id}/case-file",
        headers=auth_header(manager_user["token"]),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["conversation_id"] == conversation_id
    assert data["version"] == 1
    assert data["status"] == "active"
    assert data["entries"] == []
    assert data["tasks"] == []
    assert data["documents"] == []
    assert data["inherited_context"] == {
        "nom": "Société case",
        "forme_juridique": "SAS",
        "taille": "20-49",
        "convention_collective": "Convention test",
        "secteur_activite": "Conseil",
        "not_subject_to_ccn": False,
    }

    async with session_factory() as db:
        case_file = (
            await db.execute(
                select(CaseFile).where(CaseFile.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalar_one()
        event = (
            await db.execute(select(CaseEvent).where(CaseEvent.case_file_id == case_file.id))
        ).scalar_one()
        assert event.event_type == "created"
        assert event.organisation_context_snapshot["nom"] == "Société case"


@pytest.mark.asyncio
async def test_case_file_uses_conversation_access_control(
    client: AsyncClient,
    manager_user: dict[str, str],
    second_user: dict[str, str],
) -> None:
    _, conversation_id = await _create_org_and_conversation(client, manager_user, suffix="privée")

    response = await client.get(
        f"/api/v1/conversations/{conversation_id}/case-file",
        headers=auth_header(second_user["token"]),
    )

    assert response.status_code == 403

    mutation = await client.post(
        f"/api/v1/conversations/{conversation_id}/case-file/entries/{uuid.uuid4()}/revisions",
        headers=auth_header(second_user["token"]),
        json={"operation": "confirm", "expected_case_version": 1},
    )
    assert mutation.status_code == 403


@pytest.mark.asyncio
async def test_legacy_conversation_is_backfilled_on_first_case_file_read(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    org_id, _ = await _create_org_and_conversation(client, manager_user, suffix="legacy-parent")
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        legacy = Conversation(
            organisation_id=uuid.UUID(org_id),
            user_id=user.id,
            title="Conversation antérieure",
        )
        db.add(legacy)
        await db.commit()
        legacy_id = legacy.id

    response = await client.get(
        f"/api/v1/conversations/{legacy_id}/case-file",
        headers=auth_header(manager_user["token"]),
    )

    assert response.status_code == 200
    assert response.json()["version"] == 1
    async with session_factory() as db:
        case_file = (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == legacy_id))
        ).scalar_one()
        event = (
            await db.execute(select(CaseEvent).where(CaseEvent.case_file_id == case_file.id))
        ).scalar_one()
        assert event.actor_type == "system_backfill"


@pytest.mark.asyncio
async def test_inherited_context_stays_live_while_creation_snapshot_is_immutable(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    org_id, conversation_id = await _create_org_and_conversation(
        client, manager_user, suffix="avant"
    )
    update_response = await client.patch(
        f"/api/v1/organisations/{org_id}",
        json={"name": "Société après", "taille": "50-249"},
        headers=auth_header(manager_user["token"]),
    )
    assert update_response.status_code == 200

    response = await client.get(
        f"/api/v1/conversations/{conversation_id}/case-file",
        headers=auth_header(manager_user["token"]),
    )
    assert response.json()["inherited_context"]["nom"] == "Société après"
    assert response.json()["inherited_context"]["taille"] == "50-249"

    async with session_factory() as db:
        snapshot = (
            await db.execute(
                select(CaseEvent.organisation_context_snapshot)
                .join(CaseFile, CaseEvent.case_file_id == CaseFile.id)
                .where(CaseFile.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalar_one()
        assert snapshot["nom"] == "Société avant"
        assert snapshot["taille"] == "20-49"


@pytest.mark.asyncio
async def test_entry_revision_is_append_only_and_version_checked(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    _, conversation_id = await _create_org_and_conversation(client, manager_user, suffix="version")
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        case_file = (
            await db.execute(
                select(CaseFile).where(CaseFile.conversation_id == uuid.UUID(conversation_id))
            )
        ).scalar_one()
        original = CaseEntry(
            case_file_id=case_file.id,
            entry_type="fact",
            key="salary",
            label="Salaire mensuel",
            value_text="3 000 €",
            source_kind="user_message",
            created_by_user_id=user.id,
        )
        db.add(original)
        await db.commit()
        original_id = original.id

        replacement = await CaseFileService(db).revise_entry(
            conversation_id=uuid.UUID(conversation_id),
            entry_id=original_id,
            expected_version=1,
            user=user,
            value_text="3 200 €",
            value_json=None,
        )
        assert replacement.supersedes_entry_id == original_id

        old = await db.get(CaseEntry, original_id)
        refreshed_case = await db.get(CaseFile, case_file.id)
        assert old.status == "superseded"
        assert refreshed_case.version == 2

        with pytest.raises(HTTPException) as conflict:
            await CaseFileService(db).revise_entry(
                conversation_id=uuid.UUID(conversation_id),
                entry_id=replacement.id,
                expected_version=1,
                user=user,
                value_text="3 300 €",
                value_json=None,
            )
        assert getattr(conflict.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_user_can_confirm_contest_correct_and_archive_case_entry(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    _, conversation_id = await _create_org_and_conversation(client, manager_user, suffix="actions")
    conversation_uuid = uuid.UUID(conversation_id)
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        case_file = (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == conversation_uuid))
        ).scalar_one()
        original = CaseEntry(
            case_file_id=case_file.id,
            entry_type="fact",
            key="salary",
            label="Salaire mensuel",
            value_text="3 000 €",
            source_kind="user_message",
            created_by_user_id=user.id,
        )
        db.add(original)
        await db.commit()
        original_id = original.id

    endpoint = f"/api/v1/conversations/{conversation_id}/case-file/entries/{original_id}/revisions"
    headers = auth_header(manager_user["token"])

    confirmed = await client.post(
        endpoint,
        headers=headers,
        json={"operation": "confirm", "expected_case_version": 1},
    )
    assert confirmed.status_code == 200
    assert confirmed.headers["cache-control"] == "private, no-store"
    assert confirmed.json()["version"] == 2
    assert confirmed.json()["entries"][0]["status"] == "confirmed"

    contested = await client.post(
        endpoint,
        headers=headers,
        json={
            "operation": "contest",
            "expected_case_version": 2,
            "comment": "Le bulletin indique peut-être un autre montant",
        },
    )
    assert contested.status_code == 200
    assert contested.json()["version"] == 3
    assert contested.json()["entries"][0]["status"] == "contested"

    corrected = await client.post(
        endpoint,
        headers=headers,
        json={
            "operation": "correct",
            "expected_case_version": 3,
            "value": "3 200 €",
            "comment": "Montant vérifié sur le bulletin",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["version"] == 4
    replacement = next(
        entry for entry in corrected.json()["entries"] if entry["status"] == "confirmed"
    )
    assert replacement["value_text"] == "3 200 €"
    assert replacement["supersedes_entry_id"] == str(original_id)
    assert replacement["source_excerpt"] == "Montant vérifié sur le bulletin"
    replacement_id = replacement["id"]

    async with session_factory() as db:
        conversation = await db.get(Conversation, conversation_uuid)
        _, next_turn_context = await CaseFileService(db).observation_context(conversation)
    assert next_turn_context["entries"] == [
        {
            "id": replacement_id,
            "entry_type": "fact",
            "key": "salary",
            "label": "Salaire mensuel",
            "value_text": "3 200 €",
            "value_json": None,
            "status": "confirmed",
            "valid_from": None,
            "valid_to": None,
            "source_kind": "user_correction",
            "source_message_id": None,
            "source_excerpt": "Montant vérifié sur le bulletin",
            "source_document_id": None,
            "source_extraction_id": None,
        }
    ]

    stale = await client.post(
        f"/api/v1/conversations/{conversation_id}/case-file/entries/{replacement_id}/revisions",
        headers=headers,
        json={"operation": "archive", "expected_case_version": 3},
    )
    assert stale.status_code == 409

    archived = await client.post(
        f"/api/v1/conversations/{conversation_id}/case-file/entries/{replacement_id}/revisions",
        headers=headers,
        json={"operation": "archive", "expected_case_version": 4},
    )
    assert archived.status_code == 200
    assert archived.json()["version"] == 5
    assert all(
        entry["status"] in {"superseded", "archived"} for entry in archived.json()["entries"]
    )

    async with session_factory() as db:
        event_types = list(
            (
                await db.execute(
                    select(CaseEvent.event_type)
                    .join(CaseFile, CaseEvent.case_file_id == CaseFile.id)
                    .where(CaseFile.conversation_id == conversation_uuid)
                    .order_by(CaseEvent.created_at)
                )
            ).scalars()
        )
    assert event_types == [
        "created",
        "entry_confirmed",
        "entry_contested",
        "entry_revised",
        "entry_archived",
    ]


@pytest.mark.asyncio
async def test_gdpr_export_contains_complete_case_file(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    org_id, conversation_id = await _create_org_and_conversation(
        client, manager_user, suffix="export"
    )
    async with session_factory() as db:
        organisation = await db.get(Organisation, uuid.UUID(org_id))
        exported = await DataRetentionService(db).export_account(organisation.account_id)

    conversation = next(row for row in exported["conversations"] if row["id"] == conversation_id)
    assert conversation["case_file"]["version"] == 1
    assert conversation["case_file"]["events"][0]["event_type"] == "created"
    assert (
        conversation["case_file"]["events"][0]["organisation_context_snapshot"]["nom"]
        == "Société export"
    )


@pytest.mark.asyncio
async def test_case_file_erasure_removes_children_before_conversation_deletion(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    _, conversation_id = await _create_org_and_conversation(
        client, manager_user, suffix="effacement"
    )
    conversation_uuid = uuid.UUID(conversation_id)
    async with session_factory() as db:
        deleted = await delete_case_files_for_conversations(db, [conversation_uuid])
        await db.commit()

        assert deleted == 1
        assert (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == conversation_uuid))
        ).scalar_one_or_none() is None
        assert (await db.execute(select(CaseEvent))).scalars().all() == []


@pytest.mark.asyncio
async def test_admin_quality_exposes_raw_case_observation(
    client: AsyncClient,
    manager_user: dict[str, str],
    admin_user: dict[str, str],
) -> None:
    _, conversation_id = await _create_org_and_conversation(
        client, manager_user, suffix="observation-admin"
    )
    conversation_uuid = uuid.UUID(conversation_id)
    async with session_factory() as db:
        case_file = (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == conversation_uuid))
        ).scalar_one()
        event = CaseEvent(
            case_file_id=case_file.id,
            case_version=case_file.version,
            event_type="planner_observation",
            actor_type="llm_observer",
            raw_planner_output="SORTIE BRUTE À AFFICHER INTÉGRALEMENT",
            structured_delta={"planner_pass": 1, "case_delta": {"entries": []}},
            organisation_context_snapshot={"nom": "Société observation-admin"},
        )
        question = Message(
            conversation_id=conversation_uuid,
            role="user",
            content="Question complexe",
        )
        db.add_all([event, question])
        await db.flush()
        answer = Message(
            conversation_id=conversation_uuid,
            role="assistant",
            content="Réponse inchangée",
            rag_trace={
                "case_file_observation": {
                    "mode": "observation",
                    "case_file_id": str(case_file.id),
                    "case_file_version": case_file.version,
                    "event_ids": [str(event.id)],
                    "technical_errors": [],
                }
            },
        )
        db.add(answer)
        await db.commit()
        answer_id = answer.id

    response = await client.get(
        f"/api/v1/admin/quality/messages/{answer_id}/inspect",
        headers=auth_header(admin_user["token"]),
    )

    assert response.status_code == 200
    observation = response.json()["case_file_observations"][0]
    assert observation["raw_planner_output"] == "SORTIE BRUTE À AFFICHER INTÉGRALEMENT"
    assert observation["structured_delta"]["case_delta"] == {"entries": []}
