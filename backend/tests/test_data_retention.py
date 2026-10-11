"""Erasure ordering and tenant isolation with real foreign-key enforcement."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.base import Base
from app.models.case_file import CaseFile
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.dossier import Dossier
from app.models.fiche import Fiche
from app.models.invitation import Invitation
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.plan_invitation import PlanInvitation, PlanInvitationRedemption
from app.models.user import User
from app.services.data_retention_service import DataRetentionService


@pytest.mark.parametrize("shared_owner", [False, True])
async def test_purge_fiches_dossiers_and_redemptions_preserves_other_account(
    monkeypatch, shared_owner
):
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fks(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    index = MagicMock()
    storage = MagicMock()
    monkeypatch.setattr("app.rag.qdrant_store.get_qdrant_client", lambda: index)
    monkeypatch.setattr("app.services.storage_service.StorageService.__init__", lambda self: None)
    monkeypatch.setattr(
        "app.services.storage_service.StorageService.delete_file",
        lambda self, path: storage.delete_file(path),
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        owner = User(id=uuid.uuid4(), email="expired@example.test", full_name="Expired")
        other = User(id=uuid.uuid4(), email="active@example.test", full_name="Active")
        db.add_all([owner, other])
        await db.flush()
        account = Account(id=uuid.uuid4(), name="Expired", owner_id=owner.id)
        active = Account(id=uuid.uuid4(), name="Active", owner_id=other.id)
        db.add_all([account, active])
        await db.flush()
        org = Organisation(id=uuid.uuid4(), name="Expired org", account_id=account.id)
        other_org = Organisation(id=uuid.uuid4(), name="Active org", account_id=active.id)
        db.add_all([org, other_org])
        await db.flush()
        db.add(Membership(user_id=owner.id, organisation_id=org.id, role_in_org="owner"))
        db.add(AccountMember(account_id=account.id, user_id=other.id, role_in_org="user"))
        db.add(AccountMember(account_id=active.id, user_id=other.id, role_in_org="owner"))
        if shared_owner:
            db.add(Membership(user_id=owner.id, organisation_id=other_org.id, role_in_org="user"))
        conversation = Conversation(
            id=uuid.uuid4(), organisation_id=org.id, user_id=owner.id, title="Test"
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            id=uuid.uuid4(), conversation_id=conversation.id, role="user", content="Original"
        )
        case = CaseFile(id=uuid.uuid4(), conversation_id=conversation.id)
        detached = CaseFile(id=uuid.uuid4())
        db.add_all([message, case, detached])
        await db.flush()
        dossier = Dossier(
            id=uuid.uuid4(),
            organisation_id=org.id,
            user_id=owner.id,
            case_file_id=case.id,
            name="Dossier",
            creation_key=uuid.uuid4(),
        )
        db.add_all(
            [
                dossier,
                Dossier(
                    organisation_id=org.id,
                    user_id=owner.id,
                    case_file_id=detached.id,
                    name="Detached",
                    creation_key=uuid.uuid4(),
                ),
            ]
        )
        await db.flush()
        conversation.dossier_id = dossier.id
        doc = Document(
            id=uuid.uuid4(),
            organisation_id=org.id,
            private_dossier_id=dossier.id,
            private_conversation_id=conversation.id,
            name="doc",
            source_type="divers",
            storage_path="test/doc",
        )
        keep = Fiche(
            id=uuid.uuid4(),
            organisation_id=other_org.id,
            user_id=owner.id if shared_owner else other.id,
            title="Keep",
            content={"html": "Original"},
        )
        db.add_all(
            [
                doc,
                keep,
                Fiche(
                    organisation_id=org.id,
                    user_id=owner.id,
                    message_id=message.id,
                    title="Delete",
                    content={"html": "Original"},
                ),
            ]
        )
        plan = PlanInvitation(
            id=uuid.uuid4(),
            created_by=other.id,
            label="Invite",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(plan)
        await db.flush()
        db.add(
            PlanInvitationRedemption(
                plan_invitation_id=plan.id,
                account_id=account.id,
                user_id=owner.id,
                redeemed_at=datetime.now(UTC),
            )
        )
        db.add(
            Invitation(
                organisation_id=org.id,
                invited_by=owner.id,
                email="guest@example.test",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.commit()
        summary = await DataRetentionService(db).purge_account(account.id)
        assert summary["fiches"] == 1
        assert summary["dossiers"] == 2
        assert summary["case_files"] == 2
        assert summary["owner_retained"] == int(shared_owner)
        assert summary["storage_objects_deleted"] == 1
        assert (await db.execute(select(Account.id))).scalars().all() == [active.id]
        assert (await db.execute(select(Fiche.id))).scalars().all() == [keep.id]
        assert (await db.execute(select(Organisation.id))).scalars().all() == [other_org.id]
        for model in (
            Dossier,
            CaseFile,
            Conversation,
            Message,
            Document,
            PlanInvitationRedemption,
            Invitation,
        ):
            assert (await db.execute(select(model.id))).scalars().all() == []
        assert (
            await db.execute(select(User.id).where(User.id == owner.id))
        ).scalar_one_or_none() == (owner.id if shared_owner else None)
        assert index.delete.call_count == 1
        assert str(org.id) in str(index.delete.call_args)
        assert str(other_org.id) not in str(index.delete.call_args)
        storage.delete_file.assert_called_once_with("test/doc")
    await engine.dispose()


@pytest.mark.parametrize("failure", ["foreign_key", "index"])
async def test_failed_purge_keeps_account_and_storage_for_retry(monkeypatch, failure):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fks(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("CREATE TABLE future_dependency (org_id CHAR(32) REFERENCES organisations(id))")
        )
    index, storage = MagicMock(), MagicMock()
    if failure == "index":
        index.delete.side_effect = RuntimeError("index unavailable")
    monkeypatch.setattr("app.rag.qdrant_store.get_qdrant_client", lambda: index)
    monkeypatch.setattr("app.services.storage_service.StorageService.__init__", lambda self: None)
    monkeypatch.setattr(
        "app.services.storage_service.StorageService.delete_file",
        lambda self, path: storage.delete_file(path),
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user_id, account_id, org_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db.add(User(id=user_id, email="purge@example.test", full_name="Test"))
        await db.flush()
        db.add(Account(id=account_id, owner_id=user_id, name="Test"))
        await db.flush()
        db.add(Organisation(id=org_id, account_id=account_id, name="Test"))
        await db.flush()
        db.add(
            Document(
                organisation_id=org_id, name="doc", source_type="divers", storage_path="test/doc"
            )
        )
        if failure == "foreign_key":
            await db.execute(text("INSERT INTO future_dependency VALUES (:id)"), {"id": org_id.hex})
        await db.commit()
        with pytest.raises(IntegrityError if failure == "foreign_key" else RuntimeError):
            await DataRetentionService(db).purge_account(account_id)
        await db.rollback()
        assert await db.get(Account, account_id) is not None
        assert await db.get(Organisation, org_id) is not None
        assert (await db.execute(select(Document.id))).first() is not None
        storage.delete_file.assert_not_called()
        if failure == "foreign_key":
            index.delete.assert_not_called()
    await engine.dispose()
