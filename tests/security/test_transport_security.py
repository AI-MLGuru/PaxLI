import pytest

from apps.api.averiq_api.config import Settings
from apps.api.averiq_api.transport_security import (
    InsecureProductionConfigurationError,
    validate_production_transport_security,
)

_INSECURE_URL = "postgresql+asyncpg://averiq:averiq@localhost:5432/averiq"
_SSL_URL = "postgresql+asyncpg://averiq:averiq@db.internal:5432/averiq?sslmode=require"


def _settings(**overrides: object) -> Settings:
    return Settings(database_url=_INSECURE_URL, **overrides)  # type: ignore[arg-type]


def test_development_is_never_gated() -> None:
    validate_production_transport_security(_settings(app_env="development"))


def test_production_with_no_transport_guarantees_fails_closed() -> None:
    with pytest.raises(InsecureProductionConfigurationError):
        validate_production_transport_security(_settings(app_env="production"))


def test_production_with_internal_transport_trusted_attestation_passes() -> None:
    validate_production_transport_security(
        _settings(app_env="production", internal_transport_trusted=True)
    )


def test_production_with_real_tls_and_ssl_database_url_passes() -> None:
    validate_production_transport_security(
        Settings(
            app_env="production",
            database_url=_SSL_URL,
            storage_secure=True,
        )
    )


def test_production_with_storage_secure_but_no_database_ssl_still_fails() -> None:
    with pytest.raises(InsecureProductionConfigurationError):
        validate_production_transport_security(
            _settings(app_env="production", storage_secure=True)
        )


def test_production_with_database_ssl_but_insecure_storage_still_fails() -> None:
    with pytest.raises(InsecureProductionConfigurationError):
        validate_production_transport_security(
            Settings(app_env="production", database_url=_SSL_URL)
        )
