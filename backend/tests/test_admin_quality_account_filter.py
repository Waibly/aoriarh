from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.user import User
from tests.conftest import test_session_factory as _test_session_factory


async def test_client_question_count_links_to_same_quality_rows(
    client, admin_user, regular_user
):
    now = datetime.now(UTC)

    async with _test_session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.email == admin_user["email"]))
        ).scalar_one()
        regular = (
            await session.execute(select(User).where(User.email == regular_user["email"]))
        ).scalar_one()

        admin_org = Organisation(
            name="Organisation admin", account_id=admin.owned_account.id
        )
        other_org = Organisation(
            name="Organisation tierce", account_id=regular.owned_account.id
        )
        session.add_all([admin_org, other_org])
        await session.flush()

        recent_conversation = Conversation(
            organisation_id=admin_org.id, user_id=admin.id, title="Récente"
        )
        old_conversation = Conversation(
            organisation_id=admin_org.id, user_id=admin.id, title="Ancienne"
        )
        other_conversation = Conversation(
            organisation_id=other_org.id, user_id=regular.id, title="Autre compte"
        )
        session.add_all([recent_conversation, old_conversation, other_conversation])
        await session.flush()

        session.add_all(
            [
                Message(
                    conversation_id=recent_conversation.id,
                    role="user",
                    content="Question du compte ciblé",
                    created_at=now - timedelta(minutes=2),
                ),
                Message(
                    conversation_id=recent_conversation.id,
                    role="assistant",
                    content="Réponse du compte ciblé",
                    created_at=now - timedelta(minutes=1),
                ),
                Message(
                    conversation_id=old_conversation.id,
                    role="assistant",
                    content="Réponse trop ancienne",
                    created_at=now - timedelta(days=31),
                ),
                Message(
                    conversation_id=other_conversation.id,
                    role="assistant",
                    content="Réponse d'un autre compte",
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        await session.commit()
        account_id = admin.owned_account.id

    headers = {"Authorization": f"Bearer {admin_user['token']}"}

    quality = await client.get(
        f"/api/v1/admin/quality/conversations?account_id={account_id}&days=30",
        headers=headers,
    )
    assert quality.status_code == 200
    assert quality.json()["total"] == 1
    assert quality.json()["items"][0]["question"] == "Question du compte ciblé"

    metrics = await client.get(
        f"/api/v1/admin/quality/metrics?account_id={account_id}&days=30",
        headers=headers,
    )
    assert metrics.status_code == 200
    assert metrics.json()["total_questions"] == 1

    clients = await client.get(
        "/api/v1/admin/business/clients?page_size=200", headers=headers
    )
    assert clients.status_code == 200
    row = next(row for row in clients.json()["rows"] if row["account_id"] == str(account_id))
    assert row["questions_30d"] == 1
