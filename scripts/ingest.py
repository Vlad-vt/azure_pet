"""Embed the catalog with the INT8 ONNX model and upsert it into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from skumatch.config import get_settings
from skumatch.db.session import build_engine
from skumatch.embeddings import OnnxEmbedder
from skumatch.ingest import ingest_catalog
from skumatch.logging import configure_logging


async def _run(catalog: Path, direct: bool) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=False)
    url = settings.migration_url if direct else settings.database_url
    engine = build_engine(settings, url=url)
    embedder = OnnxEmbedder(settings.model_dir, threads=settings.embedding_threads)
    try:
        stats = await ingest_catalog(engine, embedder, catalog, settings.embedding_batch_size)
        print(json.dumps(stats))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.parquet"))
    parser.add_argument(
        "--via-pooler",
        action="store_true",
        help="use SKUMATCH_DATABASE_URL instead of the direct URL",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.catalog, direct=not args.via_pooler))


if __name__ == "__main__":
    main()
