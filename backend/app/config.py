from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "staging", "production", "test"] = "development"
    app_name: str = "FiscalGuard API"

    # Conexão direta ao Postgres (Supabase: "Session pooler" ou conexão direta).
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:54322/postgres"
    db_pool_size: int = 5

    # Autenticação Supabase: HS256 (JWT secret legado) e/ou JWKS (chaves assimétricas).
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_jwt_audience: str = "authenticated"
    supabase_service_role_key: str | None = None

    # Armazenamento
    storage_backend: Literal["local", "supabase"] = "local"
    storage_bucket: str = "fiscalguard-private"
    local_storage_dir: str = "./.storage"
    signed_url_ttl_seconds: int = 300

    # Limites de importação
    max_upload_bytes: int = 10 * 1024 * 1024
    max_files_per_upload: int = 500
    inline_import_limit: int = Field(20, description="Lotes até este tamanho são processados na requisição")
    max_csv_rows: int = 20_000

    # Compliance
    compliance_required_checks: list[str] = ["cadastro_cnpj", "cnd_federal", "crf_fgts", "cndt"]
    compliance_expiry_warning_days: int = 15

    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
