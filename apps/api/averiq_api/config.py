from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Averiq"
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
    evidence_max_bytes: int = 10 * 1024 * 1024
    evidence_encryption_key_id: str = "evidence-v1"
    evidence_encryption_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
