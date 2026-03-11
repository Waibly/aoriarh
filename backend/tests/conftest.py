import pytest
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.core.limiter import limiter
from app.main import app
from app.models.base import Base

# Disable rate limiting during tests
limiter.enabled = False

TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with test_session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncClient:
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_user(client: AsyncClient) -> dict[str, str]:
    """Register a user and upgrade to admin role."""
    from sqlalchemy import update

    from app.models.user import User

    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@test.com",
            "password": "SecurePass123!",
            "full_name": "Admin User",
        },
    )
    token = res.json()["access_token"]
    async with test_session_factory() as session:
        await session.execute(
            update(User).where(User.email == "admin@test.com").values(role="admin")
        )
        await session.commit()
    return {"email": "admin@test.com", "token": token}


@pytest.fixture
async def manager_user(client: AsyncClient) -> dict[str, str]:
    """Register a user and upgrade to manager role."""
    from sqlalchemy import update

    from app.models.user import User

    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "manager@test.com",
            "password": "SecurePass123!",
            "full_name": "Manager User",
        },
    )
    token = res.json()["access_token"]
    async with test_session_factory() as session:
        await session.execute(
            update(User).where(User.email == "manager@test.com").values(role="manager")
        )
        await session.commit()
    return {"email": "manager@test.com", "token": token}


@pytest.fixture
async def regular_user(client: AsyncClient) -> dict[str, str]:
    """Register a regular user."""
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@test.com", "password": "SecurePass123!", "full_name": "Regular User"},
    )
    token = res.json()["access_token"]
    return {"email": "user@test.com", "token": token}


@pytest.fixture
async def second_user(client: AsyncClient) -> dict[str, str]:
    """Register a second regular user."""
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "user2@test.com", "password": "SecurePass123!", "full_name": "Second User"},
    )
    token = res.json()["access_token"]
    return {"email": "user2@test.com", "token": token}
