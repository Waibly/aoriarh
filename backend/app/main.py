import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from app.core.logging import setup_logging

setup_logging(json_output=os.getenv("LOG_FORMAT", "json") == "json")

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import (
    admin_costs,
    admin_documents,
    admin_feedbacks,
    admin_judilibre,
    admin_qdrant,
    admin_syncs,
    admin_users,
    auth,
    conventions,
    conversations,
    documents,
    invitations,
    organisations,
    team,
    users,
)
from app.core.config import settings
from app.core.database import async_session_factory, get_db
from app.core.limiter import limiter
from app.core.security import hash_password
from app.models.user import User
from app.rag.qdrant_store import get_qdrant_client
from app.services.storage_service import StorageService

logger = structlog.get_logger(__name__)


_RATE_LIMIT_MESSAGES: dict[str, str] = {
    "/api/v1/auth/register": "Trop de tentatives d'inscription. Réessayez dans quelques minutes.",
    "/api/v1/auth/login": "Trop de tentatives de connexion. Réessayez dans quelques minutes.",
    "/api/v1/auth/refresh": "Trop de rafraîchissements de session. Réessayez dans quelques minutes.",
}


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    path = request.url.path

    # Check exact path matches first
    message = _RATE_LIMIT_MESSAGES.get(path)

    # Check pattern matches for dynamic routes
    if message is None:
        if "/chat" in path:
            message = "Vous envoyez trop de messages. Attendez quelques secondes avant de réessayer."
        elif request.method in ("POST", "PUT") and "/documents" in path:
            message = "Trop de documents uploadés. Limite : 30 par heure."
        else:
            message = "Trop de requêtes. Veuillez réessayer dans quelques instants."

    retry_after = exc.detail.split("per")[-1].strip() if "per" in str(exc.detail) else None

    return JSONResponse(
        status_code=429,
        content={
            "detail": message,
            **({"retry_after": retry_after} if retry_after else {}),
        },
    )


async def seed_admin() -> None:
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == settings.admin_email)
        )
        if result.scalar_one_or_none():
            logger.info("Admin account already exists: %s", settings.admin_email)
            return

        admin = User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            full_name="Admin AORIA RH",
            role="admin",
        )
        session.add(admin)
        await session.commit()
        logger.info("Admin account created: %s", settings.admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if settings.seed_admin:
        await seed_admin()
    else:
        logger.info("Admin seeding disabled (SEED_ADMIN=false)")
    yield


app = FastAPI(
    title="AORIA RH",
    description="Assistant juridique RH par IA",
    version="0.1.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

Instrumentator(
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=3600,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.minio_use_ssl:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    import time

    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)

    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        client_ip=request.client.host if request.client else None,
    )
    return response


app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(organisations.router, prefix="/api/v1/organisations", tags=["organisations"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(
    admin_documents.router, prefix="/api/v1/admin/documents", tags=["admin-documents"]
)
app.include_router(
    admin_qdrant.router, prefix="/api/v1/admin/qdrant", tags=["admin-qdrant"]
)
app.include_router(
    admin_feedbacks.router, prefix="/api/v1/admin/feedbacks", tags=["admin-feedbacks"]
)
app.include_router(
    admin_judilibre.router, prefix="/api/v1/admin/jurisprudence", tags=["admin-jurisprudence"]
)
app.include_router(
    admin_users.router, prefix="/api/v1/admin/users", tags=["admin-users"]
)
app.include_router(
    admin_syncs.router, prefix="/api/v1/admin/syncs", tags=["admin-syncs"]
)
app.include_router(
    admin_costs.router, prefix="/api/v1/admin/costs", tags=["admin-costs"]
)
app.include_router(
    conventions.router, prefix="/api/v1/conventions", tags=["conventions"]
)
app.include_router(invitations.router, prefix="/api/v1", tags=["invitations"])
app.include_router(team.router, prefix="/api/v1/team", tags=["team"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"])


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "error"

    # Qdrant
    try:
        get_qdrant_client().get_collections()
        checks["qdrant"] = "ok"
    except Exception:
        checks["qdrant"] = "error"

    # MinIO
    try:
        storage = StorageService()
        storage.client.head_bucket(Bucket=storage.bucket)
        checks["minio"] = "ok"
    except Exception:
        checks["minio"] = "error"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    code = 200 if overall == "ok" else 503
    return JSONResponse({"status": overall, **checks}, status_code=code)
