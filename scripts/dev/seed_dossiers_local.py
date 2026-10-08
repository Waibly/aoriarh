"""Seed the isolated Dossiers sandbox; refuses every other database."""
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.main import seed_admin
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User


async def main():
    if settings.postgres_host != "127.0.0.1" or settings.postgres_port != 5544:
        raise RuntimeError("This seed requires the isolated local database on port 5544")
    await seed_admin()
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.email == settings.admin_email))).scalar_one()
        account = (await db.execute(select(Account).where(Account.owner_id == user.id))).scalar_one_or_none()
        if account is None:
            account = Account(name="Essais Dossiers locaux", owner_id=user.id, plan="vip")
            db.add(account)
            await db.flush()
            db.add(AccountMember(account_id=account.id, user_id=user.id, role_in_org="manager", access_all=True))
        org = (await db.execute(select(Organisation).where(Organisation.name == "AORIA — Essais locaux"))).scalar_one_or_none()
        if org is None:
            org = Organisation(name="AORIA — Essais locaux", account_id=account.id)
            db.add(org)
            await db.flush()
            db.add(Membership(organisation_id=org.id, user_id=user.id, role_in_org="manager"))
        else:
            org.account_id = account.id
        await db.commit()
    # Bucket creation is idempotent; the storage client uses only the sandbox endpoint.
    import boto3
    client = boto3.client("s3", endpoint_url="http://" + settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key, aws_secret_access_key=settings.minio_secret_key)
    try:
        client.head_bucket(Bucket=settings.minio_bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=settings.minio_bucket)
    await engine.dispose()
    print("Compte, organisation et stockage locaux prêts.")


asyncio.run(main())
