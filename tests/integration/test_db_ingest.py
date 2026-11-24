from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from skumatch.embeddings import OnnxEmbedder

pytestmark = [pytest.mark.integration, pytest.mark.model]


async def test_extensions_and_indexes_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        exts = set((await conn.execute(text("SELECT extname FROM pg_extension"))).scalars())
        idx = {
            r[0]: r[1]
            for r in await conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'skus'")
            )
        }
    assert {"vector", "pg_trgm"} <= exts
    assert "USING hnsw (embedding vector_cosine_ops)" in idx["ix_skus_embedding_hnsw"]
    assert "USING gin (search_tsv)" in idx["ix_skus_search_tsv_gin"]
    assert "gin_trgm_ops" in idx["ix_skus_search_text_trgm_gin"]


async def test_ingest_populates_rows(engine: AsyncEngine, ingested: dict[str, float]) -> None:
    async with engine.connect() as conn:
        n, empty_tsv = (
            await conn.execute(
                text("SELECT count(*), count(*) FILTER (WHERE search_tsv = ''::tsvector) FROM skus")
            )
        ).one()
        norm = (
            await conn.execute(text("SELECT avg(vector_norm(embedding)) FROM skus"))
        ).scalar_one()
    assert n == ingested["rows"] > 0
    assert empty_tsv == 0
    assert norm == pytest.approx(1.0, abs=1e-3)


async def test_ingest_is_idempotent(
    engine: AsyncEngine, embedder: OnnxEmbedder, ingested: dict[str, float]
) -> None:
    from skumatch.ingest import build_records, upsert_records

    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT * FROM skus ORDER BY id LIMIT 1"))).mappings().one()
    rows = [
        {
            "sku_id": row["id"],
            **{k: row[k] for k in ("ean", "name", "brand", "quantity_raw", "quantity")},
            **{k: row[k] for k in ("qty_count", "qty_amount", "qty_unit")},
            "category": row["category"],
            "category_path": row["category_path"],
        }
    ]
    await upsert_records(engine, build_records(rows, embedder))
    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM skus"))).scalar_one()
    assert n == ingested["rows"]


@pytest.mark.parametrize(
    ("sql", "index"),
    [
        (
            "SELECT id FROM skus ORDER BY embedding <=> CAST(:vec AS vector) LIMIT 10",
            "ix_skus_embedding_hnsw",
        ),
        (
            "SELECT id FROM skus WHERE search_tsv @@ to_tsquery('simple', 'milch:*')",
            "ix_skus_search_tsv_gin",
        ),
        (
            "SELECT id FROM skus WHERE search_text % 'vollmilch 1000ml'",
            "ix_skus_search_text_trgm_gin",
        ),
    ],
)
async def test_retrieval_queries_can_use_indexes(
    engine: AsyncEngine, embedder: OnnxEmbedder, ingested: dict[str, float], sql: str, index: str
) -> None:
    vec = embedder.embed_one("vollmilch 1000ml")
    params = {"vec": "[" + ",".join(f"{x:.6f}" for x in vec.tolist()) + "]"}
    async with engine.begin() as conn:
        # Small CI subset: force the planner to show the index path is valid.
        await conn.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(r[0] for r in await conn.execute(text(f"EXPLAIN {sql}"), params))
    assert index in plan


def test_embeddings_are_normalised(embedder: OnnxEmbedder) -> None:
    v = embedder.embed(["Vollmilch 3,5% 1l", "VOLLM. 3.5 1L", "Haribo Goldbären 200g"])
    assert v.shape == (3, 384)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-4)
    sims = v @ v.T
    assert sims[0, 1] > sims[0, 2]
