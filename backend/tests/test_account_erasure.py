"""Deletion with enforced foreign keys, isolated storage and simulated Stripe."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import stripe
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.base import Base
from app.models.case_file import CaseDocumentLink, CaseEntry, CaseEvent, CaseFile, CaseTask
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.dossier import Dossier
from app.models.fiche import Fiche
from app.models.invitation import Invitation
from app.models.organisation import Organisation
from app.models.storage_operation import StorageOperation
from app.models.subscription import Subscription
from app.models.user import User
from app.services.user_service import UserService
from tests.conftest import auth_header


@pytest.fixture
async def erasure(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_test_db():
        async with factory() as db:
            yield db

    storage = Mock()
    index = Mock()
    monkeypatch.setattr("app.services.organisation_service.StorageService", lambda: storage)
    monkeypatch.setattr("app.services.storage_service.StorageService.__init__", lambda self: None)
    monkeypatch.setattr(
        "app.services.storage_service.StorageService.delete_file",
        lambda self, path: storage.delete_file(path),
    )
    monkeypatch.setattr("app.services.organisation_service.get_qdrant_client", lambda: index)
    monkeypatch.setattr("app.services.document_service.get_qdrant_client", lambda: index)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_local_only")
    remote = {}

    def list_subscriptions(**kwargs):
        assert kwargs["customer"] == "cus_erasure"
        return SimpleNamespace(auto_paging_iter=lambda: iter(list(remote.values())))

    listing = Mock(side_effect=list_subscriptions)
    retrieve = Mock(side_effect=lambda identifier: dict(remote[identifier]))

    def cancel_subscription(identifier):
        remote[identifier]["status"] = "canceled"
        return dict(remote[identifier])

    cancel = Mock(side_effect=cancel_subscription)
    monkeypatch.setattr("stripe.Subscription.list", listing)
    monkeypatch.setattr("stripe.Subscription.retrieve", retrieve)
    monkeypatch.setattr("stripe.Subscription.delete", cancel)
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = get_test_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            yield SimpleNamespace(
                client=client,
                factory=factory,
                storage=storage,
                index=index,
                remote=remote,
                cancel=cancel,
                retrieve=retrieve,
                listing=listing,
            )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        await engine.dispose()


async def register(env, email="erasure@test.com", *, invited=False):
    response = await env.client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "full_name": "Erasure test",
            "password": "SecurePass123!",
            "invited": invited,
        },
    )
    assert response.status_code == 201, response.text
    async with env.factory() as db:
        user = (await db.scalars(select(User).where(User.email == email))).one()
        return SimpleNamespace(
            id=user.id,
            account_id=user.owned_account.id if user.owned_account else None,
            headers=auth_header(response.json()["access_token"]),
        )


async def seed_dossier(env, actor, *, full=False, archived=False, organisation_id=None):
    async with env.factory() as db:
        if organisation_id is None:
            org = Organisation(name="Organisation to erase", account_id=actor.account_id)
            db.add(org)
            await db.flush()
            organisation_id = org.id
            from app.models.membership import Membership

            db.add(Membership(user_id=actor.id, organisation_id=org.id, role_in_org="manager"))
        case = CaseFile()
        db.add(case)
        await db.flush()
        dossier = Dossier(
            organisation_id=organisation_id,
            user_id=actor.id,
            case_file_id=case.id,
            name="Personal dossier",
            creation_key=uuid.uuid4(),
            archived_at=datetime.now(UTC) if archived else None,
        )
        db.add(dossier)
        await db.flush()
        if full:
            conversation = Conversation(
                user_id=actor.id,
                organisation_id=organisation_id,
                dossier_id=dossier.id,
            )
            db.add(conversation)
            await db.flush()
            # Legacy converted dossiers can retain their original case FK.
            case.conversation_id = conversation.id
            message = Message(conversation_id=conversation.id, role="user", content="Original")
            db.add(message)
            await db.flush()
            for scope in ("dossier", "conversation"):
                document = Document(
                    organisation_id=organisation_id,
                    uploaded_by=actor.id,
                    private_dossier_id=dossier.id if scope == "dossier" else None,
                    private_conversation_id=conversation.id if scope == "conversation" else None,
                    name=f"{scope}.txt",
                    source_type="divers",
                    storage_path=f"{organisation_id}/{dossier.id}/{scope}.txt",
                )
                db.add(document)
                await db.flush()
                extraction = DocumentExtraction(
                    document_id=document.id,
                    source_storage_path=document.storage_path,
                    source_sha256="a" * 64,
                    source_name=document.name,
                    file_format="txt",
                    extractor_version="test",
                    status="ready",
                    coverage={},
                    text_storage_path=f"{organisation_id}/{dossier.id}/{scope}-extracted.txt",
                )
                db.add(extraction)
                await db.flush()
                db.add(
                    CaseDocumentLink(
                        case_file_id=case.id,
                        document_id=document.id,
                        extraction_id=extraction.id,
                        document_name=document.name,
                        added_from_message_id=message.id,
                    )
                )
            db.add_all(
                [
                    CaseEntry(
                        case_file_id=case.id,
                        entry_type="fact",
                        label="Fact",
                        value_text="Original",
                        source_kind="user",
                        source_message_id=message.id,
                        created_by_user_id=actor.id,
                    ),
                    CaseEvent(
                        case_file_id=case.id,
                        case_version=1,
                        event_type="created",
                        actor_type="user",
                        source_message_id=message.id,
                    ),
                    CaseTask(
                        case_file_id=case.id,
                        task_type="question",
                        question="Question",
                        created_from_message_id=message.id,
                    ),
                    Fiche(
                        organisation_id=organisation_id,
                        user_id=actor.id,
                        message_id=message.id,
                        title="Fiche",
                        content={"raw": "Original"},
                    ),
                ]
            )
        await db.commit()
        return SimpleNamespace(org_id=organisation_id, dossier_id=dossier.id, case_id=case.id)


async def make_paid(env, actor, statuses=("active",)):
    async with env.factory() as db:
        account = await db.get(Account, actor.account_id)
        account.plan = "groupe"
        account.status = "active"
        account.plan_expires_at = None
        account.stripe_customer_id = "cus_erasure"
        for index, status in enumerate(statuses):
            identifier = f"sub_erasure_{index}"
            env.remote[identifier] = {"id": identifier, "status": status}
            db.add(
                Subscription(
                    account_id=account.id,
                    plan="groupe",
                    billing_cycle="monthly",
                    stripe_subscription_id=identifier,
                    status=status,
                )
            )
        await db.commit()


async def delete_account(env, actor):
    return await env.client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=actor.headers,
        json={"confirmation": "SUPPRIMER MON COMPTE"},
    )


@pytest.mark.parametrize("full,archived", [(False, False), (True, False), (True, True)])
async def test_organisation_erasure_includes_every_members_dossiers(erasure, full, archived):
    env = erasure
    owner = await register(env)
    org = await seed_dossier(env, owner, full=full, archived=archived)
    member = await register(env, "member@test.com", invited=True)
    members_dossier = await seed_dossier(
        env, member, full=full, archived=archived, organisation_id=org.org_id
    )
    outsider = await register(env, "outsider@test.com")
    preserved = await seed_dossier(env, outsider, full=True)
    response = await env.client.delete(f"/api/v1/organisations/{org.org_id}", headers=owner.headers)
    assert response.status_code == 204, response.text
    async with env.factory() as db:
        assert await db.get(Organisation, org.org_id) is None
        for dossier in (org, members_dossier):
            assert await db.get(Dossier, dossier.dossier_id) is None
            assert await db.get(CaseFile, dossier.case_id) is None
        for model in (Conversation, Document, Fiche):
            assert not (
                await db.scalars(select(model).where(model.organisation_id == org.org_id))
            ).all()
        assert await db.get(Dossier, preserved.dossier_id) is not None
        assert await db.get(CaseFile, preserved.case_id) is not None
        assert await db.get(User, member.id) is not None
        assert not (await db.scalars(select(StorageOperation))).all()
    expected_paths = (
        []
        if not full
        else [
            f"{org.org_id}/{dossier.dossier_id}/{scope}{suffix}.txt"
            for dossier in (org, members_dossier)
            for scope in ("dossier", "conversation")
            for suffix in ("", "-extracted")
        ]
    )
    assert sorted(call.args[0] for call in env.storage.delete_file.call_args_list) == sorted(
        expected_paths
    )
    env.index.delete.assert_called_once()


async def test_account_erasure_cancels_all_billable_and_unmirrored_subscriptions(erasure):
    env = erasure
    owner = await register(env)
    dossier = await seed_dossier(env, owner, full=True)
    await make_paid(
        env, owner, ("active", "trialing", "past_due", "unpaid", "paused", "incomplete")
    )
    env.remote["sub_not_mirrored"] = {"id": "sub_not_mirrored", "status": "active"}
    member = await register(env, "retained-member@test.com", invited=True)
    async with env.factory() as db:
        db.add(AccountMember(account_id=owner.account_id, user_id=member.id))
        db.add(
            Invitation(
                account_id=owner.account_id,
                invited_by=member.id,
                email="pending@test.com",
                role_in_org="user",
                expires_at=datetime.now(UTC),
            )
        )
        await db.commit()
    response = await delete_account(env, owner)
    assert response.status_code == 200, response.text
    assert env.cancel.call_count == 7
    assert all(sub["status"] == "canceled" for sub in env.remote.values())
    async with env.factory() as db:
        assert await db.get(User, owner.id) is None
        assert await db.get(Account, owner.account_id) is None
        assert await db.get(Organisation, dossier.org_id) is None
        assert await db.get(User, member.id) is not None
        assert not (await db.scalars(select(Subscription))).all()


async def test_stripe_failure_preserves_account_and_every_piece(erasure):
    env = erasure
    owner = await register(env)
    dossier = await seed_dossier(env, owner, full=True)
    await make_paid(env, owner)
    env.cancel.side_effect = stripe.error.APIConnectionError("simulated network outage")
    response = await delete_account(env, owner)
    assert response.status_code == 502, response.text
    assert "n'a pas été supprimé" in response.json()["detail"]
    async with env.factory() as db:
        assert await db.get(User, owner.id) is not None
        assert await db.get(Account, owner.account_id) is not None
        assert await db.get(Dossier, dossier.dossier_id) is not None
        assert len((await db.scalars(select(Document))).all()) == 2
        assert (await db.scalars(select(Subscription))).one().status == "active"
    env.storage.delete_file.assert_not_called()
    env.index.delete.assert_not_called()


async def test_unconfirmed_stripe_status_also_blocks_erasure(erasure):
    owner = await register(erasure)
    await make_paid(erasure, owner)
    erasure.cancel.side_effect = lambda identifier: {"id": identifier, "status": "active"}
    response = await delete_account(erasure, owner)
    assert response.status_code == 502, response.text
    async with erasure.factory() as db:
        assert await db.get(Account, owner.account_id) is not None


async def test_sql_failure_rolls_back_all_orgs_and_retry_accepts_canceled_stripe(
    erasure, monkeypatch
):
    env = erasure
    owner = await register(env)
    first = await seed_dossier(env, owner, full=True)
    second = await seed_dossier(env, owner, full=True)
    await make_paid(env, owner)
    original = UserService.delete_user_data

    async def fail_after_org_deletion(self, user_id):
        raise RuntimeError("simulated late SQL failure")

    monkeypatch.setattr(UserService, "delete_user_data", fail_after_org_deletion)
    response = await delete_account(env, owner)
    assert response.status_code == 500
    async with env.factory() as db:
        for dossier in (first, second):
            assert await db.get(Dossier, dossier.dossier_id) is not None
            assert await db.get(Organisation, dossier.org_id) is not None
        assert (await db.scalars(select(Subscription))).one().status == "active"
    env.storage.delete_file.assert_not_called()
    env.index.delete.assert_not_called()
    assert env.remote["sub_erasure_0"]["status"] == "canceled"
    monkeypatch.setattr(UserService, "delete_user_data", original)
    response = await delete_account(env, owner)
    assert response.status_code == 200, response.text
    # The first cancellation survived the SQL rollback, so retry must not cancel again.
    env.cancel.assert_called_once()
    assert env.storage.delete_file.call_count == 8


async def test_invited_user_erasure_only_removes_their_personal_data(erasure):
    env = erasure
    owner = await register(env)
    retained = await seed_dossier(env, owner, full=True)
    member = await register(env, "personal@test.com", invited=True)
    removed = await seed_dossier(env, member, full=True, organisation_id=retained.org_id)
    response = await delete_account(env, member)
    assert response.status_code == 200, response.text
    env.listing.assert_not_called()
    env.cancel.assert_not_called()
    async with env.factory() as db:
        assert await db.get(User, member.id) is None
        assert await db.get(User, owner.id) is not None
        assert await db.get(Organisation, retained.org_id) is not None
        assert await db.get(Dossier, retained.dossier_id) is not None
        assert await db.get(Dossier, removed.dossier_id) is None
        assert len((await db.scalars(select(Document))).all()) == 2
        assert not (await db.scalars(select(StorageOperation))).all()
    assert env.storage.delete_file.call_count == 4


async def test_trial_account_can_be_erased_without_stripe_configuration(erasure, monkeypatch):
    owner = await register(erasure)
    await seed_dossier(erasure, owner)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    response = await delete_account(erasure, owner)
    assert response.status_code == 200, response.text
    erasure.listing.assert_not_called()
    erasure.retrieve.assert_not_called()
    erasure.cancel.assert_not_called()
