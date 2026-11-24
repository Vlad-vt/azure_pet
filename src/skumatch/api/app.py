"""FastAPI application: hybrid SKU matching over PostgreSQL (pgvector + FTS + trigram)."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from skumatch import __version__
from skumatch.api.schemas import (
    BatchMatchRequest,
    BatchMatchResponse,
    BatchResultOut,
    CandidateOut,
    HealthResponse,
    MatchRequest,
    MatchResponse,
    SkuOut,
)
from skumatch.config import Settings, get_settings
from skumatch.db.session import build_engine, build_sessionmaker
from skumatch.embeddings import OnnxEmbedder
from skumatch.logging import configure_logging, get_logger
from skumatch.retrieval import MatchEngine, MatchResult
from skumatch.retrieval.engine import FusionConfig

log = get_logger("skumatch.api")


def _to_response(result: MatchResult) -> MatchResponse:
    return MatchResponse(
        query_normalized=result.query_normalized,
        query_quantity=result.query_quantity,
        mode=result.mode,
        candidates=[
            CandidateOut(
                sku=SkuOut.model_validate(c.sku),
                score=c.score,
                ranks=c.ranks,
                unit_match=c.unit_match,
            )
            for c in result.candidates
            if c.sku is not None
        ],
        timings_ms=result.timings_ms,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level, json=cfg.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        t0 = time.perf_counter()
        embedder = await asyncio.to_thread(
            OnnxEmbedder, cfg.model_dir, threads=cfg.embedding_threads
        )
        await asyncio.to_thread(embedder.embed_one, "warmup")
        engine = build_engine(cfg)
        app.state.match_engine = MatchEngine(
            build_sessionmaker(engine), embedder, FusionConfig.from_settings(cfg)
        )
        log.info(
            "startup_complete",
            env=cfg.env,
            model_load_ms=round((time.perf_counter() - t0) * 1000, 1),
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
        )
        try:
            yield
        finally:
            await engine.dispose()
            log.info("shutdown_complete")

    app = FastAPI(
        title="Hybrid SKU & Invoice Semantic Matching Service",
        version=__version__,
        lifespan=lifespan,
        description=(
            "Maps noisy supplier-invoice lines to catalog SKUs with Reciprocal Rank Fusion over "
            "pgvector (HNSW), PostgreSQL full-text search and pg_trgm."
        ),
    )

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            if request.url.path not in ("/healthz", "/readyz"):
                # Path, status and latency only: request bodies are never logged.
                log.info(
                    "http_request",
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                )
            structlog.contextvars.clear_contextvars()

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    def engine_of(request: Request) -> MatchEngine:
        eng: MatchEngine = request.app.state.match_engine
        return eng

    @app.get("/healthz", response_model=HealthResponse, tags=["ops"])
    async def healthz() -> HealthResponse:
        """Liveness: the process is up and the model is loaded (no DB call)."""
        return HealthResponse(status="ok", version=__version__)

    @app.get("/readyz", response_model=HealthResponse, tags=["ops"])
    async def readyz(request: Request, response: Response) -> HealthResponse:
        """Readiness: the database answers within 3 s."""
        try:
            ok = await asyncio.wait_for(engine_of(request).ping(), timeout=3.0)
        except Exception as exc:  # readiness must never raise
            log.warning("readiness_failed", error_type=type(exc).__name__)
            ok = False
        if not ok:
            response.status_code = 503
            return HealthResponse(status="unavailable", version=__version__, checks={"db": "fail"})
        return HealthResponse(status="ok", version=__version__, checks={"db": "ok"})

    @app.post("/v1/match", response_model=MatchResponse, tags=["matching"])
    async def match(body: MatchRequest, request: Request) -> MatchResponse:
        result = await engine_of(request).match(body.text, top_k=body.top_k, mode=body.mode)
        return _to_response(result)

    @app.post("/v1/match/batch", response_model=BatchMatchResponse, tags=["matching"])
    async def match_batch(body: BatchMatchRequest, request: Request) -> BatchMatchResponse:
        if len(body.items) > cfg.max_batch_size:
            raise HTTPException(413, f"batch size exceeds {cfg.max_batch_size}")
        t0 = time.perf_counter()
        results = await engine_of(request).match_batch(
            [i.text for i in body.items],
            top_k=body.top_k,
            mode=body.mode,
            concurrency=max(1, cfg.db_pool_size - 1),
        )
        return BatchMatchResponse(
            results=[
                BatchResultOut(id=item.id, result=_to_response(res))
                for item, res in zip(body.items, results, strict=True)
            ],
            timings_ms={"total": round((time.perf_counter() - t0) * 1000, 2)},
        )

    @app.get("/v1/skus/{sku_id}", response_model=SkuOut, tags=["catalog"])
    async def get_sku(sku_id: int, request: Request) -> Any:
        sku = await engine_of(request).get_sku(sku_id)
        if sku is None:
            raise HTTPException(404, "SKU not found")
        return sku

    return app


app = create_app()
