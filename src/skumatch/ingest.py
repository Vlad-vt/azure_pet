"""Batch ingestion: catalog parquet -> normalised text + ONNX embeddings -> PostgreSQL upsert."""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from skumatch.db.models import Sku
from skumatch.embeddings import OnnxEmbedder
from skumatch.logging import get_logger
from skumatch.normalize import normalize_for_search
from skumatch.normalize.text import fold_text, normalize_for_embedding

log = get_logger(__name__)


def catalog_display(brand: str, name: str, quantity_raw: str) -> str:
    """``brand name quantity`` without duplicating a brand already present in the name."""
    head = name if fold_text(name).startswith(fold_text(brand)) else f"{brand} {name}"
    return f"{head} {quantity_raw}".strip()


def sku_search_text(brand: str, name: str, quantity_raw: str) -> str:
    return normalize_for_search(catalog_display(brand, name, quantity_raw))


def sku_embedding_text(brand: str, name: str, quantity_raw: str) -> str:
    return normalize_for_embedding(catalog_display(brand, name, quantity_raw))


def load_catalog_rows(path: Path) -> list[dict[str, Any]]:
    # pyarrow is an optional ("data" extra) dependency; the API image does not need it.
    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
    return rows


def build_records(
    rows: Sequence[dict[str, Any]], embedder: OnnxEmbedder, batch_size: int = 64
) -> list[dict[str, Any]]:
    emb_texts = [sku_embedding_text(r["brand"], r["name"], r["quantity_raw"]) for r in rows]
    vectors = embedder.embed(emb_texts, batch_size=batch_size)
    records: list[dict[str, Any]] = []
    for r, vec in zip(rows, vectors, strict=True):
        records.append(
            {
                "id": int(r["sku_id"]),
                "ean": r["ean"],
                "name": r["name"],
                "brand": r["brand"],
                "quantity_raw": r["quantity_raw"],
                "quantity": r["quantity"],
                "qty_count": int(r["qty_count"]),
                "qty_amount": float(r["qty_amount"]),
                "qty_unit": r["qty_unit"],
                "category": r["category"],
                "category_path": r["category_path"],
                "search_text": sku_search_text(r["brand"], r["name"], r["quantity_raw"]),
                "embedding": vec,
            }
        )
    return records


async def upsert_records(
    engine: AsyncEngine, records: Sequence[dict[str, Any]], chunk: int = 500
) -> int:
    table = Sku.__table__.c
    updatable = [c for c in records[0] if c != "id"] if records else []
    written = 0
    async with engine.begin() as conn:
        for start in range(0, len(records), chunk):
            part = records[start : start + chunk]
            stmt = insert(Sku).values(list(part))
            stmt = stmt.on_conflict_do_update(
                index_elements=[table.id],
                set_={c: stmt.excluded[c] for c in updatable},
            )
            await conn.execute(stmt)
            written += len(part)
    return written


async def ingest_catalog(
    engine: AsyncEngine, embedder: OnnxEmbedder, catalog_path: Path, batch_size: int = 64
) -> dict[str, float]:
    t0 = time.perf_counter()
    rows = load_catalog_rows(catalog_path)
    t1 = time.perf_counter()
    records = build_records(rows, embedder, batch_size=batch_size)
    t2 = time.perf_counter()
    written = await upsert_records(engine, records)
    t3 = time.perf_counter()
    async with engine.begin() as conn:
        await conn.exec_driver_sql("ANALYZE skus")
    stats = {
        "rows": float(written),
        "load_s": round(t1 - t0, 2),
        "embed_s": round(t2 - t1, 2),
        "embed_rows_per_s": round(len(records) / max(t2 - t1, 1e-9), 1),
        "upsert_s": round(t3 - t2, 2),
    }
    log.info("ingest_complete", **stats)
    return stats
