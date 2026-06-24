"""Application settings.

Single-user, local-first. The SQLite database lives next to the backend by
default but can be overridden via the ``CRYPTO_TRACE_DB`` environment variable.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/  -> repo/backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRYPTO_TRACE_", env_file=".env")

    app_name: str = "Crypto-Trace"
    # Path to the SQLite file. Overridable with CRYPTO_TRACE_DB.
    db: str = str(DATA_DIR / "crypto_trace.db")
    # CORS origins for the local frontend dev server.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db}"


settings = Settings()
