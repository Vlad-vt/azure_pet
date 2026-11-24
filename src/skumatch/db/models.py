"""ORM models. Generated/derived columns are maintained by PostgreSQL."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    pass


class Sku(Base):
    __tablename__ = "skus"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    ean: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_raw: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[str] = mapped_column(String(32), nullable=False)
    qty_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_amount: Mapped[float] = mapped_column(Float, nullable=False)
    qty_unit: Mapped[str] = mapped_column(String(4), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    category_path: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, search_text)", persisted=True)
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_skus_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_skus_search_tsv_gin", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_skus_search_text_trgm_gin",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )
