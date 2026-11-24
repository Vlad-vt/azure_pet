"""Application settings loaded from environment variables (prefix ``SKUMATCH_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SKUMATCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["local", "test", "ci", "azure", "k8s"] = "local"
    log_level: str = "INFO"
    log_json: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://skumatch:skumatch@localhost:6432/skumatch"
    database_url_direct: str | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout_s: float = 10.0
    db_pool_recycle_s: int = 1800
    db_statement_timeout_ms: int = 5000
    db_pgbouncer: bool = False
    db_ssl: bool = False

    # Embeddings
    model_dir: Path = Path("./models/multilingual-e5-small")
    embedding_dim: int = 384
    embedding_batch_size: int = 64
    embedding_threads: int = 0  # 0 -> onnxruntime default (physical cores)

    # Retrieval / fusion
    rrf_k: int = Field(default=60, ge=1)
    rrf_w_dense: float = Field(default=0.5, ge=0.0)  # dev-tuned (docs/eval_report.md)
    rrf_w_fts: float = Field(default=0.25, ge=0.0)  # dev-tuned
    rrf_w_trgm: float = Field(default=1.5, ge=0.0)  # dev-tuned
    rrf_w_unit: float = Field(default=1.0, ge=0.0)  # dev-tuned
    rrf_unit_window: int = Field(default=20, ge=1, le=500)
    trgm_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    candidates_per_retriever: int = Field(default=50, ge=1, le=500)
    hnsw_ef_search: int = Field(default=80, ge=10, le=1000)
    max_batch_size: int = Field(default=100, ge=1, le=1000)

    def session_gucs(self) -> dict[str, str]:
        """Retrieval GUCs. Pinned per connection when not behind PgBouncer (see db.session)."""
        return {
            "hnsw.ef_search": str(max(self.hnsw_ef_search, self.candidates_per_retriever)),
            "pg_trgm.similarity_threshold": str(self.trgm_threshold),
        }

    @property
    def migration_url(self) -> str:
        return self.database_url_direct or self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
