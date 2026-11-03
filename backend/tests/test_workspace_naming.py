"""The workspace takes its first organisation's name instead of "Espace de <name>"."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.models.account import Account
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def _account_of(email: str) -> Account:
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        return (
            await session.execute(select(Account).where(Account.owner_id == user.id))
        ).scalar_one()


async def _set_account(email: str, **values) -> None:
    account = await _account_of(email)
    async with session_factory() as session:
        await session.execute(update(Account).where(Account.id == account.id).values(**values))
        await session.commit()


async def _create_org(client: AsyncClient, token: str, name: str) -> dict:
    res = await client.post(
        "/api/v1/organisations/", json={"name": name}, headers=auth_header(token)
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_signup_gives_placeholder_then_first_org_names_workspace(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    assert (await _account_of(manager_user["email"])).name == "Espace de Manager User"

    await _create_org(client, manager_user["token"], "  Boulangerie Martin ")

    assert (await _account_of(manager_user["email"])).name == "Boulangerie Martin"


@pytest.mark.asyncio
async def test_second_org_does_not_rename_workspace(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    await _set_account(manager_user["email"], plan="equipe")
    await _create_org(client, manager_user["token"], "Première SAS")
    await _create_org(client, manager_user["token"], "Seconde SARL")

    assert (await _account_of(manager_user["email"])).name == "Première SAS"


@pytest.mark.asyncio
async def test_workspace_renamed_by_owner_is_kept(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    await _set_account(manager_user["email"], name="Cabinet Dupont")
    await _create_org(client, manager_user["token"], "Client A")

    assert (await _account_of(manager_user["email"])).name == "Cabinet Dupont"


@pytest.mark.asyncio
async def test_me_flags_workspace_owner_and_rename_rejects_blank(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    org = await _create_org(client, manager_user["token"], "Acme")
    me = await client.get(
        f"/api/v1/users/me?organisation_id={org['id']}",
        headers=auth_header(manager_user["token"]),
    )
    assert me.status_code == 200
    assert me.json()["workspace_name"] == "Acme"
    assert me.json()["is_workspace_owner"] is True

    blank = await client.put(
        "/api/v1/users/me/workspace",
        json={"name": "   "},
        headers=auth_header(manager_user["token"]),
    )
    assert blank.status_code == 422
    assert (await _account_of(manager_user["email"])).name == "Acme"
