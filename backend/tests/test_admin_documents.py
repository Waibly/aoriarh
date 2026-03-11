import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, test_session_factory

# ---- Helpers ----


async def _create_document_in_db(
    *,
    org_id: uuid.UUID | None = None,
    name: str = "test.pdf",
    source_type: str = "code_travail",
    status: str = "indexed",
    file_size: int = 1024,
    file_format: str = "pdf",
    uploaded_by: uuid.UUID,
    indexation_duration_ms: int | None = 500,
) -> uuid.UUID:
    """Insert a document directly in DB (bypasses MinIO)."""
    from app.models.document import Document

    doc = Document(
        organisation_id=org_id,
        name=name,
        source_type=source_type,
        norme_niveau=4,
        norme_poids=0.9,
        storage_path=f"common/{uuid.uuid4()}_{name}",
        indexation_status=status,
        uploaded_by=uploaded_by,
        file_size=file_size,
        file_format=file_format,
        file_hash=uuid.uuid4().hex,
        indexation_duration_ms=indexation_duration_ms,
    )
    async with test_session_factory() as session:
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        return doc.id


async def _get_user_id(email: str) -> uuid.UUID:
    from sqlalchemy import select

    from app.models.user import User

    async with test_session_factory() as session:
        result = await session.execute(select(User.id).where(User.email == email))
        return result.scalar_one()


# ---- Access control ----


@pytest.mark.asyncio
async def test_stats_requires_admin(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/stats",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_all_requires_admin(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_common_requires_admin(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_manager_cannot_access_admin_endpoints(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/stats",
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 403


# ---- GET /stats ----


@pytest.mark.asyncio
async def test_stats_empty(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/stats",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_documents"] == 0
    assert data["indexed_count"] == 0
    assert data["total_storage_bytes"] == 0
    assert data["common_documents"] == 0
    assert data["org_documents"] == 0


@pytest.mark.asyncio
async def test_stats_with_documents(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")

    # Create common docs
    await _create_document_in_db(
        uploaded_by=user_id, name="common1.pdf", file_size=2048, status="indexed"
    )
    await _create_document_in_db(
        uploaded_by=user_id, name="common2.pdf", file_size=4096, status="pending"
    )
    # Create org doc
    org_id = uuid.uuid4()
    await _create_document_in_db(
        uploaded_by=user_id,
        name="org1.pdf",
        org_id=org_id,
        file_size=1024,
        status="error",
    )

    res = await client.get(
        "/api/v1/admin/documents/stats",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_documents"] == 3
    assert data["indexed_count"] == 1
    assert data["pending_count"] == 1
    assert data["error_count"] == 1
    assert data["total_storage_bytes"] == 2048 + 4096 + 1024
    assert data["common_documents"] == 2
    assert data["org_documents"] == 1


# ---- GET /all ----


@pytest.mark.asyncio
async def test_list_all_documents_empty(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_list_all_documents_returns_all(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")
    await _create_document_in_db(uploaded_by=user_id, name="common.pdf")
    await _create_document_in_db(
        uploaded_by=user_id, name="org.pdf", org_id=uuid.uuid4()
    )

    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 200
    docs = res.json()
    assert len(docs) == 2


@pytest.mark.asyncio
async def test_list_all_documents_includes_organisation_name(
    client: AsyncClient,
    admin_user: dict[str, str],
    manager_user: dict[str, str],
) -> None:
    """Documents linked to an org should have organisation_name populated."""
    # Create org via API
    org_res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Test Corp"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = uuid.UUID(org_res.json()["id"])

    user_id = await _get_user_id("admin@test.com")
    await _create_document_in_db(
        uploaded_by=user_id, name="org-doc.pdf", org_id=org_id
    )

    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(admin_user["token"]),
    )
    docs = res.json()
    assert len(docs) == 1
    assert docs[0]["organisation_name"] == "Test Corp"


@pytest.mark.asyncio
async def test_list_all_common_doc_has_null_org_name(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")
    await _create_document_in_db(uploaded_by=user_id, name="common.pdf")

    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(admin_user["token"]),
    )
    docs = res.json()
    assert len(docs) == 1
    assert docs[0]["organisation_name"] is None


# ---- GET / (list common) ----


@pytest.mark.asyncio
async def test_list_common_documents(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")
    await _create_document_in_db(uploaded_by=user_id, name="common.pdf")
    await _create_document_in_db(
        uploaded_by=user_id, name="org.pdf", org_id=uuid.uuid4()
    )

    res = await client.get(
        "/api/v1/admin/documents/",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 200
    docs = res.json()
    # Only common docs (org_id=None)
    assert len(docs) == 1
    assert docs[0]["name"] == "common.pdf"


# ---- POST / (upload) ----


@pytest.mark.asyncio
@patch("app.services.document_service.storage")
@patch("app.api.admin_documents.enqueue_ingestion", new_callable=AsyncMock)
async def test_upload_common_document(
    mock_ingestion: MagicMock,
    mock_storage: MagicMock,
    client: AsyncClient,
    admin_user: dict[str, str],
) -> None:
    mock_storage.upload_file = AsyncMock(return_value="common/test.pdf")

    res = await client.post(
        "/api/v1/admin/documents/",
        headers=auth_header(admin_user["token"]),
        files={"file": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")},
        data={"source_type": "code_travail"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "test.pdf"
    assert data["source_type"] == "code_travail"
    assert data["indexation_status"] == "pending"
    assert data["file_format"] == "pdf"
    assert data["organisation_id"] is None


@pytest.mark.asyncio
@patch("app.services.document_service.storage")
async def test_upload_rejects_invalid_format(
    mock_storage: MagicMock,
    client: AsyncClient,
    admin_user: dict[str, str],
) -> None:
    res = await client.post(
        "/api/v1/admin/documents/",
        headers=auth_header(admin_user["token"]),
        files={"file": ("test.exe", BytesIO(b"fake"), "application/octet-stream")},
        data={"source_type": "code_travail"},
    )
    assert res.status_code == 400


# ---- DELETE /{document_id} ----


@pytest.mark.asyncio
@patch("app.services.document_service.DocumentService._delete_qdrant_chunks")
@patch("app.services.document_service.storage")
async def test_delete_common_document(
    mock_storage: MagicMock,
    mock_qdrant: MagicMock,
    client: AsyncClient,
    admin_user: dict[str, str],
) -> None:
    user_id = await _get_user_id("admin@test.com")
    doc_id = await _create_document_in_db(uploaded_by=user_id, name="to-delete.pdf")

    res = await client.delete(
        f"/api/v1/admin/documents/{doc_id}",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 204

    # Verify it's gone
    res2 = await client.get(
        "/api/v1/admin/documents/",
        headers=auth_header(admin_user["token"]),
    )
    assert all(d["id"] != str(doc_id) for d in res2.json())


@pytest.mark.asyncio
async def test_delete_nonexistent_document_returns_404(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    fake_id = uuid.uuid4()
    res = await client.delete(
        f"/api/v1/admin/documents/{fake_id}",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 404


# ---- POST /{document_id}/reindex ----


@pytest.mark.asyncio
@patch("app.services.document_service.DocumentService._delete_qdrant_chunks")
@patch("app.api.admin_documents.enqueue_ingestion", new_callable=AsyncMock)
async def test_reindex_error_document(
    mock_ingestion: MagicMock,
    mock_qdrant: MagicMock,
    client: AsyncClient,
    admin_user: dict[str, str],
) -> None:
    user_id = await _get_user_id("admin@test.com")
    doc_id = await _create_document_in_db(
        uploaded_by=user_id, name="failed.pdf", status="error"
    )

    res = await client.post(
        f"/api/v1/admin/documents/{doc_id}/reindex",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["indexation_status"] == "pending"


@pytest.mark.asyncio
async def test_reindex_indexed_document_rejected(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")
    doc_id = await _create_document_in_db(
        uploaded_by=user_id, name="ok.pdf", status="indexed"
    )

    res = await client.post(
        f"/api/v1/admin/documents/{doc_id}/reindex",
        headers=auth_header(admin_user["token"]),
    )
    assert res.status_code == 400


# ---- indexation_duration_ms field ----


@pytest.mark.asyncio
async def test_document_includes_indexation_duration(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")
    await _create_document_in_db(
        uploaded_by=user_id,
        name="timed.pdf",
        indexation_duration_ms=1234,
    )

    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(admin_user["token"]),
    )
    docs = res.json()
    assert docs[0]["indexation_duration_ms"] == 1234


@pytest.mark.asyncio
async def test_pending_document_has_null_duration(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    user_id = await _get_user_id("admin@test.com")
    await _create_document_in_db(
        uploaded_by=user_id,
        name="pending.pdf",
        status="pending",
        indexation_duration_ms=None,
    )

    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(admin_user["token"]),
    )
    docs = res.json()
    assert docs[0]["indexation_duration_ms"] is None
