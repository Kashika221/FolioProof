"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    # llama-3.3-70b-versatile was retired by Groq. gpt-oss-120b was
    # benchmarked against gpt-oss-20b and qwen3.6-27b on a real CV:
    # only 120b extracted every employer and project link, and qwen
    # could not satisfy JSON mode at all.
    groq_model: str = "openai/gpt-oss-120b"

    github_token: str = ""


    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "folioproof"
    # Atlas (mongodb+srv) needs an SRV DNS lookup plus a TLS handshake, and a
    # free-tier cluster may be cold. 1.5s is fine for localhost but flaps on
    # cloud; 5s costs nothing when the server is actually up.
    mongodb_timeout_ms: int = 5000
    upload_dir: str = "./data/uploads"
    cache_dir: str = "./data/cache"


    @property
    def upload_path(self) -> Path:
        p = (BACKEND_ROOT / self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cache_path(self) -> Path:
        p = (BACKEND_ROOT / self.cache_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())


settings = Settings()
