"""Shared fixtures. Integration tests need ``SKUMATCH_TEST_DATABASE_URL`` (pgvector) and the
ONNX model in ``SKUMATCH_MODEL_DIR`` (default ``models/multilingual-e5-small``)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from skumatch.retrieval import MatchEngine

from skumatch.config import Settings
from skumatch.db.session import build_engine, build_sessionmaker
from skumatch.embeddings import OnnxEmbedder

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get("SKUMATCH_TEST_DATABASE_URL")
MODEL_DIR = Path(os.environ.get("SKUMATCH_MODEL_DIR", ROOT / "models/multilingual-e5-small"))
CATALOG = ROOT / "data/catalog.parquet"
# Subset keeps CI fast; it contains every SKU referenced by the integration assertions.
SUBSET_SIZE = 1500


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_db = pytest.mark.skip(reason="SKUMATCH_TEST_DATABASE_URL not set")
    skip_model = pytest.mark.skip(reason=f"ONNX model not found in {MODEL_DIR}")
    for item in items:
        if "integration" in item.keywords and not TEST_DB_URL:
            item.add_marker(skip_db)
        if "model" in item.keywords and not (MODEL_DIR / "model.onnx").exists():
            item.add_marker(skip_model)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    assert TEST_DB_URL
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="test",
        database_url=TEST_DB_URL,
        model_dir=MODEL_DIR,
    )


@pytest.fixture(scope="session")
def embedder() -> OnnxEmbedder:
    return OnnxEmbedder(MODEL_DIR, threads=2)


@pytest.fixture(scope="session")
def migrated_db() -> str:
    assert TEST_DB_URL
    env = {**os.environ, "SKUMATCH_DATABASE_URL": TEST_DB_URL, "SKUMATCH_DATABASE_URL_DIRECT": ""}
    env.pop("SKUMATCH_DATABASE_URL_DIRECT")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True
    )
    return TEST_DB_URL


@pytest_asyncio.fixture(scope="session")
async def engine(migrated_db: str, test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(test_settings)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def ingested(engine: AsyncEngine, embedder: OnnxEmbedder) -> dict[str, float]:
    from skumatch.ingest import build_records, load_catalog_rows, upsert_records

    rows = load_catalog_rows(CATALOG)[:SUBSET_SIZE]
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE skus"))
    records = build_records(rows, embedder)
    written = await upsert_records(engine, records)
    async with engine.begin() as conn:
        await conn.execute(text("ANALYZE skus"))
    return {"rows": float(written)}


@pytest_asyncio.fixture(scope="session")
async def match_engine(
    engine: AsyncEngine, embedder: OnnxEmbedder, ingested: dict[str, float]
) -> MatchEngine:
    from skumatch.retrieval import MatchEngine

    return MatchEngine(build_sessionmaker(engine), embedder)
