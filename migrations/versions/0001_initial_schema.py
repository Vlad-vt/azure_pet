"""Initial schema: skus table with HNSW (cosine), FTS GIN and trigram GIN indexes.

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # On Azure Flexible Server both extensions must be allow-listed via `azure.extensions`.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "skus",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("ean", sa.String(14), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("quantity_raw", sa.Text(), nullable=False),
        sa.Column("quantity", sa.String(32), nullable=False),
        sa.Column("qty_count", sa.Integer(), nullable=False),
        sa.Column("qty_amount", sa.Float(), nullable=False),
        sa.Column("qty_unit", sa.String(4), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("category_path", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_tsv",
            TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True),
        ),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_skus_embedding_hnsw",
        "skus",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_skus_search_tsv_gin", "skus", ["search_tsv"], postgresql_using="gin")
    op.create_index(
        "ix_skus_search_text_trgm_gin",
        "skus",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_table("skus")
