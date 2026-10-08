import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.case_file import CaseDocumentLink, CaseEntry, CaseFile
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.membership import Membership
from app.models.user import User
from app.services.case_file_service import CaseFileService
from app.services.document_access import authorize_private_document
from app.services.document_service import DocumentService
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory
from tests.test_case_files import _create_org_and_conversation


async def new_dossier(client, actor, org, **kwargs):
    response = await client.post(
        "/api/v1/dossiers/",
        headers=auth_header(actor["token"]),
        json={
            "name": "Élections CSE",
            "organisation_id": org,
            "creation_key": str(uuid.uuid4()),
            **kwargs,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_shared_context_multiple_chats_and_masking(client, manager_user):
    org, free = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    entry = await client.post(
        f"/api/v1/dossiers/{d['id']}/entries",
        headers=headers,
        json={
            "label": "Date",
            "value": "  Le 15 décembre\nà confirmer.  ",
            "expected_case_version": 1,
        },
    )
    assert entry.status_code == 200, entry.text
    assert (
        entry.json()["case_file"]["entries"][0]["value_text"] == "  Le 15 décembre\nà confirmer.  "
    )
    ids = []
    for _ in range(2):
        result = await client.post(
            "/api/v1/conversations/",
            headers=headers,
            json={"organisation_id": org, "dossier_id": d["id"]},
        )
        assert result.status_code == 201, result.text
        ids.append(result.json()["id"])
        case = await client.get(f"/api/v1/conversations/{ids[-1]}/case-file", headers=headers)
        assert case.status_code == 200, case.text
        assert case.json()["id"] == d["case_file"]["id"]
        assert case.json()["conversation_id"] == ids[-1]
    free_case = (
        await client.get(f"/api/v1/conversations/{free}/case-file", headers=headers)
    ).json()
    assert free_case["entries"] == []
    assert (
        await client.delete(f"/api/v1/conversations/?organisation_id={org}", headers=headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/conversations/?organisation_id={org}", headers=headers)
    ).json() == []
    detail = (await client.get(f"/api/v1/dossiers/{d['id']}", headers=headers)).json()
    assert len(detail["conversations"]) == 2
    assert (await client.get(f"/api/v1/conversations/{ids[0]}", headers=headers)).status_code == 200


async def test_conversion_is_selective_and_repeatable_and_cannot_move(client, manager_user):
    org, conv = await _create_org_and_conversation(client, manager_user)
    headers = auth_header(manager_user["token"])
    async with session_factory() as db:
        case = (
            await db.execute(select(CaseFile).where(CaseFile.conversation_id == uuid.UUID(conv)))
        ).scalar_one()
        kept = CaseEntry(
            case_file_id=case.id,
            entry_type="fact",
            label="Date",
            value_text="Original",
            source_kind="user",
            status="confirmed",
        )
        omitted = CaseEntry(
            case_file_id=case.id,
            entry_type="fact",
            label="Autre",
            value_text="Local",
            source_kind="user",
            status="active",
        )
        db.add_all(
            [
                kept,
                omitted,
                Message(
                    conversation_id=uuid.UUID(conv), role="assistant", content="  Réponse brute\n "
                ),
            ]
        )
        await db.commit()
        entry_id = str(kept.id)
    key = str(uuid.uuid4())
    d = await new_dossier(
        client,
        manager_user,
        org,
        conversation_id=conv,
        entry_ids=[entry_id],
        expected_case_version=1,
        creation_key=key,
    )
    assert [e["value_text"] for e in d["case_file"]["entries"]] == ["Original"]
    same = await new_dossier(
        client,
        manager_user,
        org,
        conversation_id=conv,
        entry_ids=[entry_id],
        expected_case_version=1,
        creation_key=key,
    )
    assert same["id"] == d["id"]
    result = await client.post(
        "/api/v1/dossiers/",
        headers=headers,
        json={
            "organisation_id": org,
            "name": "Autre",
            "creation_key": str(uuid.uuid4()),
            "conversation_id": conv,
            "expected_case_version": 1,
        },
    )
    assert result.status_code == 409
    result = await client.patch(
        f"/api/v1/conversations/{conv}",
        headers=headers,
        json={"title": "X", "dossier_id": str(uuid.uuid4())},
    )
    assert result.status_code == 422
    chat = (await client.get(f"/api/v1/conversations/{conv}", headers=headers)).json()
    assert chat["messages"][0]["content"] == "  Réponse brute\n "


async def test_archive_conflicts_and_owner_isolation(client, manager_user, regular_user):
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    async with session_factory() as db:
        other = (
            await db.execute(select(User).where(User.email == regular_user["email"]))
        ).scalar_one()
        db.add(Membership(user_id=other.id, organisation_id=uuid.UUID(org), role_in_org="user"))
        await db.commit()
    denied = await client.get(
        f"/api/v1/dossiers/{d['id']}", headers=auth_header(regular_user["token"])
    )
    assert denied.status_code == 404
    hidden = await client.get(
        f"/api/v1/dossiers/?organisation_id={org}", headers=auth_header(regular_user["token"])
    )
    assert hidden.json()["items"] == []
    archived = await client.patch(
        f"/api/v1/dossiers/{d['id']}",
        headers=headers,
        json={"expected_version": 1, "archived": True},
    )
    assert archived.status_code == 200
    refused = await client.post(
        "/api/v1/conversations/",
        headers=headers,
        json={"organisation_id": org, "dossier_id": d["id"]},
    )
    assert refused.status_code == 409
    refused = await client.post(
        f"/api/v1/dossiers/{d['id']}/entries",
        headers=headers,
        json={"label": "x", "value": "y", "expected_case_version": 1},
    )
    assert refused.status_code == 409
    stale = await client.patch(
        f"/api/v1/dossiers/{d['id']}",
        headers=headers,
        json={"expected_version": 1, "archived": False},
    )
    assert stale.status_code == 409
    restored = await client.patch(
        f"/api/v1/dossiers/{d['id']}",
        headers=headers,
        json={"expected_version": 2, "archived": False},
    )
    assert restored.status_code == 200


async def test_private_documents_never_in_company_library_or_other_scope(client, manager_user):
    org, conv = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    other = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    async with session_factory() as db:
        user = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        private = Document(
            organisation_id=uuid.UUID(org),
            private_dossier_id=uuid.UUID(d["id"]),
            name="Secret.txt",
            source_type="divers",
            storage_path="private",
            uploaded_by=user.id,
        )
        company = Document(
            organisation_id=uuid.UUID(org),
            name="Entreprise.txt",
            source_type="divers",
            storage_path="company",
            uploaded_by=user.id,
        )
        db.add_all([private, company])
        await db.flush()
        db.add(
            CaseDocumentLink(
                case_file_id=uuid.UUID(d["case_file"]["id"]),
                document_id=private.id,
                document_name=private.name,
            )
        )
        await db.commit()
        private_id = str(private.id)
        assert [doc.name for doc in await DocumentService(db).list_documents(uuid.UUID(org))] == [
            "Entreprise.txt"
        ]
        with pytest.raises(HTTPException):
            await DocumentService(db).get_document(private.id, uuid.UUID(org))
        await authorize_private_document(db, private, user, dossier_id=uuid.UUID(d["id"]))
        with pytest.raises(HTTPException):
            await authorize_private_document(db, private, user, dossier_id=uuid.UUID(other["id"]))
    for endpoint in [
        f"/api/v1/documents/{org}/{private_id}",
        f"/api/v1/documents/{org}/{private_id}/download",
        f"/api/v1/conversations/sources/{private_id}/full-content",
    ]:
        assert (await client.get(endpoint, headers=headers)).status_code == 404
    removed = await client.post(
        f"/api/v1/dossiers/{d['id']}/documents/actions",
        headers=headers,
        json={"operation": "remove", "document_id": private_id, "expected_case_version": 1},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["documents"] == []
    async with session_factory() as db:
        private = await db.get(Document, uuid.UUID(private_id))
        user = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        with pytest.raises(HTTPException):
            await authorize_private_document(db, private, user, dossier_id=uuid.UUID(d["id"]))


def test_search_private_filter_excludes_even_same_organisation():
    from qdrant_client import QdrantClient, models

    from app.rag.access_filter import build_org_access_filter

    client = QdrantClient(":memory:")
    client.create_collection(
        "test", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE)
    )
    client.upsert(
        "test",
        [
            models.PointStruct(
                id=i,
                vector=[1.0, 0.0],
                payload={"organisation_id": "org", "document_id": str(i), "private": i == 2},
            )
            for i in [1, 2]
        ],
    )
    public, _ = client.scroll("test", scroll_filter=build_org_access_filter("org"))
    assert [p.id for p in public] == [1]
    allowed, _ = client.scroll(
        "test", scroll_filter=build_org_access_filter("org", authorized_private_document_ids=["2"])
    )
    assert {p.id for p in allowed} == {1, 2}
    other, _ = client.scroll(
        "test",
        scroll_filter=build_org_access_filter("other", authorized_private_document_ids=["2"]),
    )
    assert other == []


async def test_confirmed_entries_are_protected_and_private_chat_documents_not_promoted(
    client, manager_user
):
    from app.services.case_file_service import CaseFileApplyError

    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    added = (
        await client.post(
            f"/api/v1/dossiers/{d['id']}/entries",
            headers=headers,
            json={"label": "Date confirmée", "value": "15 décembre", "expected_case_version": 1},
        )
    ).json()
    entry = added["case_file"]["entries"][0]
    async with session_factory() as db:
        case = await db.get(CaseFile, uuid.UUID(d["case_file"]["id"]))
        service = CaseFileService(db)
        with pytest.raises(CaseFileApplyError, match="case_entry_requires_user_confirmation"):
            await service.apply_planner_delta(
                case_file=case,
                expected_version=case.version,
                case_delta={"entries": [{"operation": "archive", "target_entry_id": entry["id"]}]},
                case_tasks=[],
                documents=[],
                source_message_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                observation_event_id=uuid.uuid4(),
            )
        result = await service.apply_planner_delta(
            case_file=case,
            expected_version=case.version,
            case_delta={"entries": []},
            case_tasks=[],
            documents=[{"document_id": str(uuid.uuid4()), "extraction_id": str(uuid.uuid4())}],
            source_message_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            observation_event_id=uuid.uuid4(),
        )
        assert result["applied"] is False
        assert (await db.get(CaseEntry, uuid.UUID(entry["id"]))).status == "confirmed"
        private = Document(
            organisation_id=uuid.UUID(org),
            private_conversation_id=uuid.uuid4(),
            name="Pièce réservée à un échange",
            source_type="divers",
            storage_path="private",
        )
        db.add(private)
        await db.flush()
        with pytest.raises(
            CaseFileApplyError, match="conversation_document_cannot_update_shared_case"
        ):
            await service.apply_planner_delta(
                case_file=case,
                expected_version=case.version,
                case_delta={"entries": [{"source_document_id": str(private.id)}]},
                case_tasks=[],
                documents=[],
                source_message_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                observation_event_id=uuid.uuid4(),
            )


async def test_document_metadata_is_local_and_stale_updates_are_rejected(client, manager_user):
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    async with session_factory() as db:
        doc = Document(
            organisation_id=uuid.UUID(org),
            name="Entreprise.txt",
            source_type="divers",
            storage_path="company",
        )
        db.add(doc)
        await db.flush()
        db.add(
            CaseDocumentLink(
                case_file_id=uuid.UUID(d["case_file"]["id"]),
                document_id=doc.id,
                document_name=doc.name,
            )
        )
        await db.commit()
        doc_id = str(doc.id)
    payload = {
        "operation": "rename",
        "document_id": doc_id,
        "name": "Pièce locale",
        "description": "  Note\noriginale  ",
        "expected_case_version": 1,
    }
    result = await client.post(
        f"/api/v1/dossiers/{d['id']}/documents/actions", headers=headers, json=payload
    )
    assert result.status_code == 200, result.text
    assert result.json()["documents"][0]["description"] == payload["description"]
    assert (
        await client.post(
            f"/api/v1/dossiers/{d['id']}/documents/actions", headers=headers, json=payload
        )
    ).status_code == 409
    async with session_factory() as db:
        assert (await db.get(Document, uuid.UUID(doc_id))).name == "Entreprise.txt"


async def test_history_search_and_archived_conversation_mutation(client, manager_user):
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    async with session_factory() as db:
        owner = (
            await db.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        chats = [
            Conversation(
                organisation_id=uuid.UUID(org),
                user_id=owner.id,
                dossier_id=uuid.UUID(d["id"]),
                title=f"Conversation {i}",
            )
            for i in range(52)
        ]
        chats[0].title = "Aiguille_100%"
        db.add_all(chats)
        await db.commit()
        cid = str(chats[0].id)
    detail = (
        await client.get(f"/api/v1/dossiers/{d['id']}?q=Aiguille_100%25", headers=headers)
    ).json()
    assert [c["title"] for c in detail["conversations"]] == ["Aiguille_100%"]
    recent = (
        await client.get(f"/api/v1/conversations/?organisation_id={org}", headers=headers)
    ).json()
    assert next(c for c in recent if c["id"] == cid)["dossier_name"] == d["name"]
    await client.patch(
        f"/api/v1/dossiers/{d['id']}",
        headers=headers,
        json={"expected_version": 1, "archived": True},
    )
    assert (await client.delete(f"/api/v1/conversations/{cid}", headers=headers)).status_code == 409


async def test_named_chat_uses_the_existing_stream_endpoint_with_shared_references(
    client, manager_user, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.services import conversation_document_service
    from app.services.billing_service import BillingService

    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user["token"])
    created = (
        await client.post(
            "/api/v1/conversations/",
            headers=headers,
            json={"organisation_id": org, "dossier_id": d["id"]},
        )
    ).json()
    async with session_factory() as db:
        doc = Document(
            organisation_id=uuid.UUID(org),
            private_dossier_id=uuid.UUID(d["id"]),
            name="Contexte privé.txt",
            source_type="divers",
            storage_path="private",
        )
        db.add(doc)
        await db.flush()
        # The executor is stopped before extraction access. The link references
        # a real document; extraction FK is disabled only in the SQLite fixture.
        extraction_id = uuid.uuid4()
        db.add(
            CaseDocumentLink(
                case_file_id=uuid.UUID(d["case_file"]["id"]),
                document_id=doc.id,
                document_name=doc.name,
                extraction_id=extraction_id,
            )
        )
        await db.commit()
        document_id = str(doc.id)
    monkeypatch.setattr(
        BillingService, "get_account_for_organisation", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(BillingService, "check_question_quota", AsyncMock())
    captured = []

    async def stop_before_read(db, conversation, user, references, **kwargs):
        captured.extend(references)
        raise HTTPException(409, "technical-test-stop-before-generation")

    monkeypatch.setattr(
        conversation_document_service, "read_conversation_documents", stop_before_read
    )
    response = await client.post(
        f"/api/v1/conversations/{created['id']}/chat/stream",
        headers=headers,
        json={"message": "Question de test", "document_references": []},
    )
    assert response.status_code == 409, response.text
    assert [ref["document_id"] for ref in captured] == [document_id]


async def test_delete_project_erases_private_content_and_preserves_company_documents(
    client, manager_user, regular_user, monkeypatch
):
    from unittest.mock import AsyncMock, Mock
    from app.models.dossier import Dossier
    from app.models.storage_operation import StorageOperation
    from app.services import document_service, storage_operation_service
    cleanup = AsyncMock(return_value={"pending": 3})
    chunks = Mock()
    monkeypatch.setattr(storage_operation_service, "finish_pending_storage_deletes", cleanup)
    monkeypatch.setattr(document_service.DocumentService, "_delete_qdrant_chunks", chunks)
    org, free = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    headers = auth_header(manager_user['token'])
    r = await client.post('/api/v1/conversations/', headers=headers,
                          json={'organisation_id': org, 'dossier_id': d['id']})
    conv_id = uuid.UUID(r.json()['id'])
    async with session_factory() as db:
        owner = (await db.get(Conversation, conv_id)).user_id
        docs = [Document(organisation_id=uuid.UUID(org), name=name, source_type='divers',
                         storage_path=name, uploaded_by=owner, **scope)
                for name, scope in [('company', {}), ('private', {'private_dossier_id': uuid.UUID(d['id'])}),
                                    ('conversation', {'private_conversation_id': conv_id})]]
        db.add_all(docs)
        db.add(Message(conversation_id=conv_id, role='user', content='Private message'))
        db.add(CaseEntry(case_file_id=uuid.UUID(d['case_file']['id']), entry_type='fact',
                         label='Private fact', value_text='Private', source_kind='user'))
        await db.flush()
        for doc in docs:
            db.add(CaseDocumentLink(case_file_id=uuid.UUID(d['case_file']['id']),
                                   document_id=doc.id, document_name=doc.name))
        await db.commit()
        company_id = docs[0].id
    url = f"/api/v1/dossiers/{d['id']}?expected_version=1"
    assert (await client.delete(url, headers=auth_header(regular_user['token']))).status_code == 404
    assert (await client.delete(url.replace('=1', '=99'), headers=headers)).status_code == 409
    # Hidden conversations must also be physically erased.
    await client.delete(f'/api/v1/conversations/{conv_id}', headers=headers)
    response = await client.delete(url, headers=headers)
    assert response.status_code == 204, response.text
    assert (await client.get(f"/api/v1/dossiers/{d['id']}", headers=headers)).status_code == 404
    async with session_factory() as db:
        assert await db.get(Dossier, uuid.UUID(d['id'])) is None
        assert await db.get(CaseFile, uuid.UUID(d['case_file']['id'])) is None
        assert await db.get(Conversation, conv_id) is None
        assert await db.get(Conversation, uuid.UUID(free)) is not None
        assert list((await db.scalars(select(Document.id))).all()) == [company_id]
        assert list((await db.scalars(select(Message).where(Message.conversation_id == conv_id))).all()) == []
        assert list((await db.scalars(select(CaseEntry))).all()) == []
        assert {o.target_path for o in (await db.scalars(select(StorageOperation))).all()} == {'private', 'conversation'}
    assert chunks.call_count == 2
    cleanup.assert_awaited_once()


async def test_dossier_references_use_current_links_and_exclude_retired_uploads(client, manager_user):
    from datetime import UTC, datetime
    from app.services.dossier_service import DossierService
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    async with session_factory() as db:
        user = (await db.scalars(select(User).where(User.email == manager_user['email']))).one()
        service = DossierService(db)
        dossier = await service.get(uuid.UUID(d['id']), user)
        old = Document(organisation_id=uuid.UUID(org), private_dossier_id=dossier.id,
                       name='old', source_type='divers', storage_path='old', retired_at=datetime.now(UTC))
        new = Document(organisation_id=uuid.UUID(org), private_dossier_id=dossier.id,
                       name='new', source_type='divers', storage_path='new')
        db.add_all([old, new]); await db.flush()
        extraction_id = uuid.uuid4()
        db.add(CaseDocumentLink(case_file_id=dossier.case_file_id, document_id=new.id,
                               extraction_id=extraction_id, document_name='new'))
        await db.commit()
        result = await service.conversation_references(dossier, [
            {'document_id':str(old.id), 'extraction_id':str(uuid.uuid4())},
            {'document_id':str(uuid.uuid4()), 'extraction_id':str(uuid.uuid4()), 'scope':'dossier'},
        ])
        assert result == [{'document_id':str(new.id), 'extraction_id':str(extraction_id),
                           'name':'new', 'scope':'dossier'}]


async def test_unprepared_dossier_document_is_not_silently_ignored(client, manager_user):
    from app.services.dossier_service import DossierService
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    async with session_factory() as db:
        user = (await db.scalars(select(User).where(User.email == manager_user['email']))).one()
        service = DossierService(db)
        dossier = await service.get(uuid.UUID(d['id']), user)
        doc = Document(organisation_id=uuid.UUID(org), private_dossier_id=dossier.id,
                       name='not-ready', source_type='divers', storage_path='pending')
        db.add(doc); await db.flush()
        db.add(CaseDocumentLink(case_file_id=dossier.case_file_id, document_id=doc.id, document_name=doc.name))
        await db.commit()
        with pytest.raises(HTTPException) as err:
            await service.conversation_references(dossier, [])
        assert err.value.status_code == 409


async def test_unavailable_document_link_can_be_removed_without_a_document_id(client, manager_user):
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    async with session_factory() as db:
        link = CaseDocumentLink(case_file_id=uuid.UUID(d['case_file']['id']), document_id=None,
                                document_name='Deleted company document')
        db.add(link); await db.commit(); link_id = str(link.id)
    result = await client.post(f"/api/v1/dossiers/{d['id']}/documents/actions",
        headers=auth_header(manager_user['token']), json={'operation':'remove', 'link_id':link_id,
                                                       'expected_case_version':1})
    assert result.status_code == 200, result.text
    assert result.json()['documents'] == []


async def test_failed_upload_association_cleans_new_file_and_keeps_original(client, manager_user, monkeypatch):
    from unittest.mock import AsyncMock
    from sqlalchemy import update
    from app.services.billing_service import BillingService
    from app.services import storage_operation_service
    org, _ = await _create_org_and_conversation(client, manager_user)
    d = await new_dossier(client, manager_user, org)
    monkeypatch.setattr(BillingService, 'get_account_for_organisation', AsyncMock(return_value=object()))
    monkeypatch.setattr(BillingService, 'ensure_plan_active', lambda *args: None)
    monkeypatch.setattr(BillingService, 'check_document_limit', AsyncMock())
    monkeypatch.setattr(storage_operation_service, 'finish_pending_storage_deletes', AsyncMock())
    uploaded_ids = []
    async def upload(self, *args, **kwargs):
        doc = Document(organisation_id=uuid.UUID(org), private_dossier_id=uuid.UUID(d['id']),
                       name='new', source_type='divers', storage_path='new')
        self.db.add(doc)
        await self.db.execute(update(CaseFile).where(CaseFile.id == uuid.UUID(d['case_file']['id'])).values(version=2))
        await self.db.commit(); uploaded_ids.append(doc.id)
        return doc
    monkeypatch.setattr(DocumentService, 'upload_document', upload)
    result = await client.post(f"/api/v1/dossiers/{d['id']}/documents?expected_case_version=1",
        headers=auth_header(manager_user['token']), files={'file':('new.txt',b'text','text/plain')})
    assert result.status_code == 409, result.text
    assert len(uploaded_ids) == 1
    async with session_factory() as db:
        assert await db.get(Document, uploaded_ids[0]) is None
        assert (await db.get(CaseFile, uuid.UUID(d['case_file']['id']))).version == 2


async def test_recent_dossiers_are_ordered_before_pagination(client, manager_user):
    from datetime import UTC, datetime, timedelta
    from app.models.dossier import Dossier
    org, _ = await _create_org_and_conversation(client, manager_user)
    first = await new_dossier(client, manager_user, org)
    second = await new_dossier(client, manager_user, org)
    async with session_factory() as db:
        old = await db.get(Dossier, uuid.UUID(first['id']))
        old.pinned = True; old.updated_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
    response = await client.get(f'/api/v1/dossiers/?organisation_id={org}&order=recent&limit=1',
                                headers=auth_header(manager_user['token']))
    assert response.status_code == 200
    assert [d['id'] for d in response.json()['items']] == [second['id']]
    assert response.json()['has_more'] is True
