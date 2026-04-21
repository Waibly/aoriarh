from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aoriarh"
    postgres_user: str = "aoriarh"
    postgres_password: str  # OBLIGATOIRE — pas de défaut

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str  # OBLIGATOIRE — pas de défaut
    minio_secret_key: str  # OBLIGATOIRE — pas de défaut
    minio_bucket: str = "aoriarh-documents"
    minio_use_ssl: bool = False

    # OpenAI
    openai_api_key: str  # OBLIGATOIRE — pas de défaut

    # Voyage AI
    voyage_api_key: str  # OBLIGATOIRE — pas de défaut
    voyage_embedding_model: str = "voyage-law-2"

    # LLM
    llm_model: str = "gpt-5-mini"

    # Auth / JWT
    secret_key: str  # OBLIGATOIRE — pas de défaut
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 3
    algorithm: str = "HS256"

    # Brevo (email)
    brevo_api_key: str  # OBLIGATOIRE — pas de défaut
    support_email: str = "hello@aoriarh.fr"
    frontend_url: str = "http://localhost:3000"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # Stripe price IDs — fill in from the Stripe dashboard once products are created.
    # If empty, billing endpoints return 501 Not Implemented (module disabled).
    stripe_price_solo_monthly: str = ""
    stripe_price_solo_yearly: str = ""
    stripe_price_equipe_monthly: str = ""
    stripe_price_equipe_yearly: str = ""
    stripe_price_groupe_monthly: str = ""
    stripe_price_groupe_yearly: str = ""

    # Add-ons (all monthly recurring, prorated when added mid-cycle)
    stripe_price_addon_user: str = ""
    stripe_price_addon_org: str = ""
    stripe_price_addon_docs: str = ""

    # Booster (one-shot, +500 questions)
    stripe_price_booster: str = ""

    # Redirect URLs after Stripe checkout / portal
    stripe_checkout_success_url: str = ""  # defaults to frontend_url + "/settings/billing?success=1"
    stripe_checkout_cancel_url: str = ""   # defaults to frontend_url + "/settings/billing?canceled=1"
    stripe_portal_return_url: str = ""     # defaults to frontend_url + "/settings/billing"

    # Admin seed
    seed_admin: bool = False  # Activer uniquement en dev / premier déploiement
    admin_email: str = "hello@aoriarh.fr"
    admin_password: str = ""  # OBLIGATOIRE si seed_admin=true

    # Judilibre API (PISTE — OAuth2 Client Credentials)
    judilibre_client_id: str = ""
    judilibre_client_secret: str = ""
    judilibre_base_url: str = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"
    judilibre_oauth_url: str = "https://oauth.piste.gouv.fr/api/oauth/token"

    # Légifrance / KALI API (PISTE — même OAuth2, API différente)
    # Si client_id/secret vides, utilise les credentials Judilibre (même app PISTE)
    legifrance_client_id: str = ""
    legifrance_client_secret: str = ""
    legifrance_base_url: str = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app"
    legifrance_oauth_url: str = "https://oauth.piste.gouv.fr/api/oauth/token"

    # Redis (task queue)
    redis_url: str = "redis://localhost:6379"

    # CORS
    backend_cors_origins: str = '["http://localhost:3000"]'

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if v in ("dev-secret-key", "changeme", "secret", ""):
            raise ValueError(
                "SECRET_KEY non sécurisé. "
                "Générer avec : python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if len(v) < 32:
            raise ValueError("SECRET_KEY doit faire au moins 32 caractères")
        return v

    @model_validator(mode="after")
    def validate_admin_seed(self) -> "Settings":
        if not self.seed_admin:
            return self
        if not self.admin_password or self.admin_password in ("admin123", "password", "changeme"):
            raise ValueError(
                "SEED_ADMIN=true mais ADMIN_PASSWORD non sécurisé — choisir un mot de passe fort"
            )
        if len(self.admin_password) < 16:
            raise ValueError(
                "SEED_ADMIN=true mais ADMIN_PASSWORD trop court — minimum 16 caractères"
            )
        if not self.admin_email:
            raise ValueError("SEED_ADMIN=true mais ADMIN_EMAIL non défini")
        return self

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        import json

        value = self.backend_cors_origins.strip()
        if value.startswith("["):
            return json.loads(value)
        return [origin.strip() for origin in value.split(",") if origin.strip()]


settings = Settings()
