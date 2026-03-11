import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health")
    data = response.json()
    assert "status" in data
    assert data["status"] in ("ok", "degraded")
    # Detailed checks are present
    for key in ("postgres", "qdrant", "minio"):
        assert key in data
        assert data[key] in ("ok", "error")
