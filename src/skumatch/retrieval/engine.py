"""Hybrid matching engine: dense (pgvector HNSW) + lexical (FTS, trigram) fused with RRF."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from skumatch.config import Settings
from skumatch.db.models import Sku
from skumatch.embeddings import OnnxEmbedder
from skumatch.normalize import Quantity, normalize_for_search, parse_quantity
from skumatch.normalize.text import normalize_for_embedding
from skumatch.retrieval.fusion import reciprocal_rank_fusion
from skumatch.retrieval.sql import SET_LOCALS, build_tsquery, retrieval_sql


class MatchMode(StrEnum):
    HYBRID = "hybrid"
    DENSE = "dense"
    LEXICAL = "lexical"


_RETRIEVERS: dict[MatchMode, tuple[str, ...]] = {
    MatchMode.HYBRID: ("dense", "fts", "trgm"),
    MatchMode.DENSE: ("dense",),
    MatchMode.LEXICAL: ("fts", "trgm"),
}


@dataclass(slots=True)
class MatchCandidate:
    sku_id: int
    score: float
    ranks: dict[str, int] = field(default_factory=dict)
    unit_match: bool | None = None
    sku: dict[str, Any] | None = None


@dataclass(slots=True)
class MatchResult:
    query_normalized: str
    query_quantity: str | None
    mode: MatchMode
    candidates: list[MatchCandidate]
    timings_ms: dict[str, float]


@dataclass(frozen=True, slots=True)
class FusionConfig:
    k: int = 60
    w_dense: float = 0.5
    w_fts: float = 0.25
    w_trgm: float = 1.5
    w_unit: float = 1.0  # bonus list: candidates whose pack size equals the query's
    unit_window: int = 20
    candidates: int = 50
    trgm_threshold: float = 0.15
    ef_search: int = 80

    @classmethod
    def from_settings(cls, s: Settings) -> FusionConfig:
        return cls(
            k=s.rrf_k,
            w_dense=s.rrf_w_dense,
            w_fts=s.rrf_w_fts,
            w_trgm=s.rrf_w_trgm,
            w_unit=s.rrf_w_unit,
            unit_window=s.rrf_unit_window,
            candidates=s.candidates_per_retriever,
            trgm_threshold=s.trgm_threshold,
            ef_search=s.hnsw_ef_search,
        )

    def weights(self) -> dict[str, float]:
        return {"dense": self.w_dense, "fts": self.w_fts, "trgm": self.w_trgm, "unit": self.w_unit}


@dataclass(slots=True)
class RetrievalLists:
    normalized: str
    query_quantity: Quantity | None
    ranked: dict[str, list[int]]
    unit_ok: dict[int, bool]
    skus: dict[int, dict[str, Any]]
    db_ms: float


def fuse(
    lists: RetrievalLists, mode: MatchMode, cfg: FusionConfig, top_k: int
) -> list[tuple[int, float]]:
    """Pure fusion step: RRF over the mode's retrievers (+ unit-agreement list for hybrid)."""
    ranked = {r: lists.ranked.get(r, []) for r in _RETRIEVERS[mode]}
    weights = cfg.weights()
    inputs: dict[str, list[int]] = dict(ranked)
    if mode is MatchMode.HYBRID and lists.query_quantity is not None and cfg.w_unit > 0:
        # Unit agreement is a 4th ranked list: unit-matching candidates in pre-fusion order,
        # restricted to the pre-fusion top `unit_window` so it re-orders, never injects.
        pre = reciprocal_rank_fusion(ranked, weights, cfg.k)[: cfg.unit_window]
        inputs["unit"] = [i for i, _ in pre if lists.unit_ok.get(i)]
    return reciprocal_rank_fusion(inputs, weights, cfg.k)[:top_k]


def _vec_literal(vec: npt.NDArray[np.float32]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec.tolist()) + "]"


class MatchEngine:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        embedder: OnnxEmbedder,
        fusion: FusionConfig | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._embedder = embedder
        self.fusion = fusion or FusionConfig()

    # ------------------------------------------------------------------ public
    async def match(
        self,
        query: str,
        *,
        top_k: int = 5,
        mode: MatchMode = MatchMode.HYBRID,
        fusion: FusionConfig | None = None,
        include_sku: bool = True,
    ) -> MatchResult:
        vec: npt.NDArray[np.float32] | None = None
        t0 = time.perf_counter()
        if "dense" in _RETRIEVERS[mode]:
            vec = await asyncio.to_thread(self._embedder.embed_one, normalize_for_embedding(query))
        embed_ms = (time.perf_counter() - t0) * 1000
        result = await self._match_with_vector(query, vec, top_k, mode, fusion, include_sku)
        result.timings_ms["embed"] = round(embed_ms, 2)
        result.timings_ms["total"] = round((time.perf_counter() - t0) * 1000, 2)
        return result

    async def match_batch(
        self,
        queries: Sequence[str],
        *,
        top_k: int = 5,
        mode: MatchMode = MatchMode.HYBRID,
        concurrency: int = 4,
    ) -> list[MatchResult]:
        vecs: list[npt.NDArray[np.float32] | None] = [None] * len(queries)
        if "dense" in _RETRIEVERS[mode] and queries:
            texts = [normalize_for_embedding(q) for q in queries]
            matrix = await asyncio.to_thread(self._embedder.embed, texts)
            vecs = list(matrix)
        sem = asyncio.Semaphore(concurrency)

        async def _one(q: str, v: npt.NDArray[np.float32] | None) -> MatchResult:
            async with sem:
                return await self._match_with_vector(q, v, top_k, mode, None, True)

        return list(await asyncio.gather(*(_one(q, v) for q, v in zip(queries, vecs, strict=True))))

    async def get_sku(self, sku_id: int) -> dict[str, Any] | None:
        async with self._sessionmaker() as session:
            row = await session.get(Sku, sku_id)
            return _sku_dict(row) if row else None

    async def ping(self) -> bool:
        async with self._sessionmaker() as session:
            value = (await session.execute(text("SELECT 1"))).scalar_one()
            return bool(value == 1)

    # ------------------------------------------------------------------ internals
    async def retrieve(
        self,
        query: str,
        vec: npt.NDArray[np.float32] | None = None,
        *,
        retrievers: tuple[str, ...] = ("dense", "fts", "trgm"),
        fusion: FusionConfig | None = None,
    ) -> RetrievalLists:
        """Run the retrievers once and return their ranked lists (used by the API and eval)."""
        cfg = fusion or self.fusion
        normalized = normalize_for_search(query)
        q_qty = parse_quantity(normalized)
        if "dense" in retrievers and vec is None:
            vec = await asyncio.to_thread(self._embedder.embed_one, normalize_for_embedding(query))
        params: dict[str, Any] = {
            "k": cfg.candidates,
            "q": normalized,
            "tsq": build_tsquery(normalized),
        }
        if vec is not None:
            params["vec"] = _vec_literal(vec)

        t0 = time.perf_counter()
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                SET_LOCALS,
                {
                    "ef_search": str(max(cfg.ef_search, cfg.candidates)),
                    "trgm_threshold": str(cfg.trgm_threshold),
                },
            )
            rows = (await session.execute(retrieval_sql(retrievers), params)).all()
            ranked: dict[str, list[int]] = {r: [] for r in retrievers}
            for sku_id, retriever, _rank, _score in sorted(rows, key=lambda r: (r[1], r[2])):
                ranked[retriever].append(int(sku_id))
            candidate_ids = {i for ids in ranked.values() for i in ids}
            skus = await self._load_skus(session, candidate_ids) if candidate_ids else {}
        db_ms = (time.perf_counter() - t0) * 1000

        unit_ok: dict[int, bool] = {}
        if q_qty is not None:
            for sku_id, sku in skus.items():
                unit_ok[sku_id] = q_qty.matches(
                    Quantity(sku["qty_count"], sku["qty_amount"], sku["qty_unit"])
                )
        return RetrievalLists(normalized, q_qty, ranked, unit_ok, skus, round(db_ms, 2))

    async def _match_with_vector(
        self,
        query: str,
        vec: npt.NDArray[np.float32] | None,
        top_k: int,
        mode: MatchMode,
        fusion: FusionConfig | None,
        include_sku: bool,
    ) -> MatchResult:
        cfg = fusion or self.fusion
        retrievers = _RETRIEVERS[mode]
        lists = await self.retrieve(query, vec, retrievers=retrievers, fusion=cfg)
        fused = fuse(lists, mode, cfg, top_k)
        rank_of = {r: {i: n for n, i in enumerate(ids, start=1)} for r, ids in lists.ranked.items()}
        has_qty = lists.query_quantity is not None
        candidates = [
            MatchCandidate(
                sku_id=sku_id,
                score=round(score, 6),
                ranks={r: rank_of[r][sku_id] for r in retrievers if sku_id in rank_of[r]},
                unit_match=lists.unit_ok.get(sku_id, False) if has_qty else None,
                sku=lists.skus.get(sku_id) if include_sku else None,
            )
            for sku_id, score in fused
        ]
        return MatchResult(
            query_normalized=lists.normalized,
            query_quantity=lists.query_quantity.token() if lists.query_quantity else None,
            mode=mode,
            candidates=candidates,
            timings_ms={"db": lists.db_ms},
        )

    @staticmethod
    async def _load_skus(session: AsyncSession, ids: set[int]) -> dict[int, dict[str, Any]]:
        stmt = select(
            Sku.id,
            Sku.ean,
            Sku.name,
            Sku.brand,
            Sku.quantity_raw,
            Sku.quantity,
            Sku.qty_count,
            Sku.qty_amount,
            Sku.qty_unit,
            Sku.category,
            Sku.category_path,
        ).where(Sku.id.in_(ids))
        return {int(r.id): dict(r._mapping) for r in (await session.execute(stmt)).all()}


def _sku_dict(row: Sku) -> dict[str, Any]:
    return {
        "id": row.id,
        "ean": row.ean,
        "name": row.name,
        "brand": row.brand,
        "quantity_raw": row.quantity_raw,
        "quantity": row.quantity,
        "qty_count": row.qty_count,
        "qty_amount": row.qty_amount,
        "qty_unit": row.qty_unit,
        "category": row.category,
        "category_path": row.category_path,
    }
