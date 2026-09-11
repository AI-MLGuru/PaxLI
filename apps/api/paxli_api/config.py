from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PaxLI"
    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    api_prefix: str = "/v1"
    session_ttl_minutes: int = 30
    database_url: str = "postgresql+asyncpg://averiq:averiq@localhost:5432/averiq"
    storage_endpoint: str = "localhost:9000"
    storage_access_key: str = "averiq"
    storage_secret_key: str = "change-me"
    storage_bucket: str = "verification-evidence"
    storage_secure: bool = False
    internal_transport_trusted: bool = False
    evidence_max_bytes: int = 10 * 1024 * 1024
    evidence_encryption_key_id: str = "evidence-v1"
    evidence_encryption_key: str | None = None

    # Foundation-010: static, environment-driven rate limit configuration --
    # deliberately not tenant-configurable (Foundation-010 discovery
    # decision #10: avoids building a second policy-governance layer for
    # what is an operational admission-control concern).
    rate_limit_auth_attempts_per_window: int = 20
    rate_limit_auth_window_seconds: int = 60
    rate_limit_verification_create_per_window: int = 60
    rate_limit_verification_create_window_seconds: int = 60
    rate_limit_evidence_submit_per_window: int = 120
    rate_limit_evidence_submit_window_seconds: int = 60
    rate_limit_credential_manage_per_window: int = 10
    rate_limit_credential_manage_window_seconds: int = 60
    rate_limit_window_retention_hours: int = 24
    # Dedicated to network-source hashing only -- never the credential
    # secret-hashing key, never the evidence-encryption key (Foundation-010
    # review guardrail #4).
    rate_limit_network_source_hmac_key_id: str = "rate-limit-source-v1"
    rate_limit_network_source_hmac_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
