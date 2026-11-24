from __future__ import annotations

import time
from collections.abc import AsyncIterator

import numpy as np
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from skumatch.api.app import create_app
from skumatch.config import Settings
from skumatch.embeddings import OnnxEmbedder
from skumatch.retrieval import MatchEngine, MatchMode

pytestmark = [pytest.mark.integration, pytest.mark.model]


@pytest_asyncio.fixture(scope="session")
async def client(test_settings: Settings, ingested: dict[str, float]) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings.model_copy(update={"log_json": False}))
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_healthz_and_readyz(client: AsyncClient) -> None:
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {"db": "ok"}


@pytest.mark.parametrize(
    ("line", "expected_name"),
    [
        ("FERRERO NUTELLA 0,4 KG", "Nutella"),
        ("C0CA-C0LA ZER0 SUGAR 0,33L", "Coca-Cola Zero Sugar"),
        ("LINDT EDELBITTER MILD 90% 100G", "Edelbitterschokolade Mild 90%"),
    ],
)
async def test_match_finds_expected_sku(client: AsyncClient, line: str, expected_name: str) -> None:
    r = await client.post("/v1/match", json={"text": line, "top_k": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    names = [c["sku"]["name"] for c in body["candidates"]]
    assert expected_name in names[:3]
    top = body["candidates"][0]
    assert top["score"] > 0 and top["ranks"]
    assert body["query_quantity"] is not None
    assert {"db", "embed", "total"} <= set(body["timings_ms"])


async def test_unit_normalisation_matches_pack_size(client: AsyncClient) -> None:
    r = await client.post("/v1/match", json={"text": "Ferrero Nutella 400 g", "top_k": 3})
    top = r.json()["candidates"][0]
    assert top["sku"]["quantity"] == "400g" and top["unit_match"] is True


@pytest.mark.parametrize("mode", [m.value for m in MatchMode])
async def test_all_modes(client: AsyncClient, mode: str) -> None:
    r = await client.post("/v1/match", json={"text": "nutella 400g", "mode": mode})
    assert r.status_code == 200
    assert r.json()["mode"] == mode
    ranks = r.json()["candidates"][0]["ranks"]
    expected = {"dense": {"dense"}, "lexical": {"fts", "trgm"}, "hybrid": {"dense", "fts", "trgm"}}
    assert set(ranks) <= expected[mode]


async def test_batch(client: AsyncClient) -> None:
    items = [
        {"id": "l1", "text": "FERRERO NUTELLA 400G"},
        {"id": "l2", "text": "COCA COLA ZERO SUGAR 330ML"},
    ]
    r = await client.post("/v1/match/batch", json={"items": items, "top_k": 2})
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["id"] for x in res] == ["l1", "l2"]
    assert all(len(x["result"]["candidates"]) == 2 for x in res)


async def test_get_sku_and_404(client: AsyncClient) -> None:
    r = await client.get("/v1/skus/3")
    assert r.status_code == 200 and r.json()["name"] == "Nutella"
    assert (await client.get("/v1/skus/999999999")).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{"text": ""}, {"text": "x" * 600}, {"text": "milk", "top_k": 0}, {"text": "a", "foo": 1}],
)
async def test_validation_errors(client: AsyncClient, payload: dict[str, object]) -> None:
    assert (await client.post("/v1/match", json=payload)).status_code == 422


async def test_hostile_input_is_safe(client: AsyncClient) -> None:
    for text in ["'; DROP TABLE skus; --", "a & b | !c <-> (d)", "%%%___", "🙂🙂🙂"]:
        r = await client.post("/v1/match", json={"text": text})
        assert r.status_code == 200
    assert (await client.get("/v1/skus/3")).status_code == 200


async def test_cpu_latency_budget(match_engine: MatchEngine) -> None:
    """Warm single-line hybrid latency on CPU (embed + 3 retrievers + fusion)."""
    lines = ["FERRERO NUTELLA 400G", "MILSA. VOLLMILCH 3,5% 1L", "HARIBO GOLDB. 200G"] * 10
    await match_engine.match(lines[0])
    samples = []
    for line in lines:
        t0 = time.perf_counter()
        await match_engine.match(line)
        samples.append((time.perf_counter() - t0) * 1000)
    p95 = float(np.percentile(samples, 95))
    assert p95 < 250, f"p95 {p95:.1f} ms"


async def test_match_survives_dropped_connections_without_pre_ping(
    test_settings: Settings, embedder: OnnxEmbedder, ingested: dict[str, float]
) -> None:
    """Azure runs with pool_pre_ping off: a killed pooled connection must cost one retry only."""
    from sqlalchemy import text

    from skumatch.db.session import build_engine, build_sessionmaker

    cfg = test_settings.model_copy(update={"db_pool_pre_ping": False})
    eng = build_engine(cfg)
    try:
        engine = MatchEngine(build_sessionmaker(eng), embedder, session_gucs=cfg.session_gucs())
        assert (await engine.match("FERRERO NUTELLA 400G")).candidates
        admin = build_engine(test_settings)
        async with admin.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE application_name = 'skumatch' AND pid <> pg_backend_pid()"
                )
            )
        await admin.dispose()
        result = await engine.match("FERRERO NUTELLA 400G")
        assert result.candidates[0].sku is not None
    finally:
        await eng.dispose()
