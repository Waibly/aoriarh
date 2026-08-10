import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "postgres_password": "postgres-test-password",
        "minio_access_key": "minio-test-access",
        "minio_secret_key": "minio-test-secret",
        "openai_api_key": "openai-test-key",
        "voyage_api_key": "voyage-test-key",
        "secret_key": "s" * 64,
        "brevo_api_key": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_capacity_defaults_bound_database_and_worker_concurrency():
    configured = _settings()

    assert configured.db_pool_size == 8
    assert configured.db_max_overflow == 4
    assert configured.db_pool_timeout == 10
    assert configured.worker_db_pool_size == 4
    assert configured.worker_db_max_overflow == 4
    assert configured.worker_max_jobs == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("db_pool_size", 0),
        ("db_max_overflow", -1),
        ("db_pool_timeout", 0),
        ("worker_db_pool_size", 0),
        ("worker_db_max_overflow", -1),
        ("worker_max_jobs", 0),
    ],
)
def test_capacity_settings_reject_invalid_values(field: str, value: int):
    with pytest.raises(ValidationError):
        _settings(**{field: value})
