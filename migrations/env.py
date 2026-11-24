"""Alembic async environment. Uses the *direct* (non-PgBouncer) URL for DDL."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from skumatch.config import get_settings
from skumatch.db.models import Base
from skumatch.db.session import build_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return get_settings().migration_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = get_settings().model_copy(update={"db_pgbouncer": False})
    engine = build_engine(settings, url=_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
