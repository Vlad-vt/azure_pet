"""Async engine factory with a conservative pool sized for Burstable B1ms (see ADR-001)."""

from __future__ import annotations

import ssl
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from skumatch.config import Settings


def build_engine(settings: Settings, url: str | None = None) -> AsyncEngine:
    connect_args: dict[str, Any] = {
        "timeout": 10,
        "command_timeout": settings.db_statement_timeout_ms / 1000 * 2,
        "server_settings": {"application_name": "skumatch"},
    }
    if settings.db_pgbouncer:
        # PgBouncer transaction pooling: no server-side prepared statements, no startup GUCs.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args.pop("server_settings")
    if settings.db_ssl:
        ctx = ssl.create_default_context()
        connect_args["ssl"] = ctx
    return create_async_engine(
        url or settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=settings.db_pool_recycle_s,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(engine, expire_on_commit=False)
