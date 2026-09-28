from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = "development"

    # Database
    database_url: str = Field(
        ..., description="Async SQLAlchemy URL (postgresql+asyncpg://...)"
    )
    database_url_sync: str = Field(
        ..., description="Sync SQLAlchemy URL for Alembic (postgresql+psycopg://...)"
    )

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str
    supabase_storage_bucket: str = "receipts"

    # GoldAPI.io
    goldapi_key: str = ""
    # Currencies the daily job fetches. Each one costs 2 calls/day (gold +
    # silver) against the free tier's 100/month — keep this to one.
    price_currencies: str = "AED"

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def price_currencies_list(self) -> list[str]:
        return [c.strip().upper() for c in self.price_currencies.split(",") if c.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
