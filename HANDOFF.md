# HANDOFF — Hybrid SKU & Invoice Semantic Matching Service

> Single source of truth for resuming work on any device. Updated at the end of every stage.
> Execution log: GitHub Issue #1 (`Execution Log & Cross-Device Handoff`).

## Current Stage & Last Tag
- **Current stage:** Stage 2 — Database, Indexes & ONNX Ingestion ✅ (Stage 0 Azure cleanup still pending sign-in)
- **Last tag:** `v0.2-db-ingest`

| Tag | Commit | Notes |
|---|---|---|
| `v0.0-bootstrap` | `18ced0b` | repo skeleton |
| `v0.1-data` | `0bd95e0` | data + generator |
| `v0.2-db-ingest` | see `git log --grep "feat(stage-2)"` | schema, indexes, ingestion |

> Tags are created locally in the cloud session; its git proxy rejects tag pushes (HTTP 403).
> From a workstation: `git fetch origin && git tag -a <tag> <commit> -m <tag> && git push origin --tags`.

## Completed Deliverables
- `PROJECT_PLAN.md`, `CLAUDE.md` (agent rules + budget guardrails), `HANDOFF.md`
- `pyproject.toml` (Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, Pydantic v2,
  structlog, onnxruntime; extras `data`, `eval`, `dev`), `uv.lock`
- Tooling: `ruff` (lint + format), `mypy --strict`, `pytest` + `pytest-asyncio`, `Makefile`
- `docker-compose.yml`: `pgvector/pgvector:pg16` + PgBouncer (transaction pooling) + optional API
- `.env.example` (placeholders only), `.gitignore` (secrets, `mlruns/`, models, raw dumps)
- `src/skumatch/config.py` (pydantic-settings, `SKUMATCH_` prefix, pool 5+5 defaults)
- `src/skumatch/logging.py` (structlog JSON; redacts `query`/`text`/`vector`/`embedding`/`body`)
- GitHub Issue #1 created
- **Stage 1:** `scripts/fetch_off.py` — Open Food Facts HF Parquet (`food.parquet`, 4.8M rows) →
  8,000 German SKUs (`data/catalog.parquet`, 308 KB, committed; ODbL)
- `src/skumatch/normalize/` — unit parsing/canonicalisation (`0,5 kg`→`500g`, `6er 330ml`→`6x330ml`),
  umlaut/ß folding, token-level OCR repair (`C0CA`→`coca`, `O,5L`→`0,5l`), article-number stripping
- `src/skumatch/data/synth.py` — deterministic `InvoiceLineGenerator(seed=42)`, 4 slices
  (`abbreviations`, `unit_swap`, `ocr_typos`, `hard_negatives` with recorded sibling SKU)
- `data/golden_eval.jsonl` — 1,200 labelled lines (300/slice; 289 dev / 911 test)
- `docs/data_report.md`, `scripts/data_report.py`, `scripts/download_model.py`
- Tests: `tests/unit/test_normalize.py`, `tests/unit/test_synth.py`
- **Stage 2:** `src/skumatch/db/` (SQLAlchemy 2.0 model + async engine factory, B1ms pool 5+5,
  PgBouncer mode disables asyncpg statement caches), Alembic (`alembic.ini`, `migrations/`,
  revision `0001`: `vector` + `pg_trgm`, `skus` with generated `tsvector`,
  HNSW `vector_cosine_ops (m=16, ef_construction=64)`, GIN tsvector, GIN `gin_trgm_ops`)
- `src/skumatch/embeddings/onnx_embedder.py` — INT8 ONNX `multilingual-e5-small` (Xenova export,
  pinned revision), mean pooling + L2 norm, `query: ` prefix on both sides (symmetric task)
- `src/skumatch/ingest.py` + `scripts/ingest.py` — batch embed + idempotent upsert + `ANALYZE`
- `scripts/explain.py` → `docs/explain_analyze.md` (fails if any retriever seq-scans)
- Tests: `tests/conftest.py`, `tests/integration/test_db_ingest.py` (7 integration tests)

## Verified Metrics & Commands
```text
ruff check .        -> All checks passed
mypy src (strict)   -> Success: no issues found
pytest tests/unit   -> 3 passed (bootstrap)
# Stage 1
make data                       -> 109,929 DE candidates -> 8,000 deduplicated SKUs
generate_synthetic (seed=42)    -> 1,200 lines; sha256 364202e885e9a566… (byte-identical on rerun)
pytest                          -> 34 passed
# Stage 2 (4 vCPU dev container, PostgreSQL 16 + pgvector 0.6)
make ingest     -> 8,000 rows; embed 14.2 s (565 rows/s); upsert+HNSW 17.6 s; table 38 MB
make explain    -> HNSW 3.6 ms, GIN tsvector 3.9 ms, GIN trigram 10.7 ms (all index scans)
embed_one       -> p50 2.9 ms, p95 4.2 ms (1 thread); process RSS ~470 MB with model loaded
pytest (with SKUMATCH_TEST_DATABASE_URL) -> 41 passed
```

## Azure Resources State
- Subscription check (`az account show`) and Resource Group cleanup: **pending** — the cloud
  session is waiting for the device-code sign-in (`az login --tenant <tenant> --use-device-code`).
- No Azure resources have been created by this project yet.

## Known Issues / Decisions
- Cloud dev container has no Docker daemon; local integration tests run against a native
  PostgreSQL 16 + `postgresql-16-pgvector` install. CI uses the `pgvector/pgvector:pg16` service container.
- Hugging Face downloads use plain HTTPS (`HF_HUB_DISABLE_XET=1`) because the Xet CAS host is not
  on the network allow-list.
- Work is pushed to `main` (explicitly requested) and mirrored to `claude/hopeful-cori-a644hr`.
- Catalog dedup key is normalised `brand + name + quantity`; OFF still contains near-duplicates
  under different brand spellings (e.g. `Coca-Cola` vs `Cola Cola`) — kept on purpose, they are
  realistic and make Recall@1 honest.
- Hard negatives require *discriminating evidence* (a name token the sibling lacks, or a
  different pack size); ambiguous sibling pairs are rejected by the generator.
- The raw 7.7 GB dump lives in `data/raw/` (git-ignored); only the compact catalog is committed.
- FTS uses the `simple` config on pre-folded text (no stemming); abbreviations are handled with
  prefix terms (`'vollm':*`). Migrations always use the *direct* URL (never PgBouncer).
- Local integration DB: `SKUMATCH_TEST_DATABASE_URL=postgresql+asyncpg://skumatch:skumatch@localhost:5432/skumatch_test`.

## Exact Next Steps
1. Complete `az login`, verify the subscription is *Azure for Students*, list and delete old RGs,
   purge soft-deleted Key Vaults / Cognitive Services accounts.
2. Stage 3: Hybrid RRF engine (`src/skumatch/retrieval/`) + FastAPI (`/v1/match`,
   `/v1/match/batch`, `/v1/skus/{id}`, `/healthz`, `/readyz`) + integration tests → `v0.3-hybrid-api`.

### Quick Resume Prompt for Another Device
```text
You are continuing the "Hybrid SKU & Invoice Semantic Matching Service" in repo Vlad-vt/azure_pet.
Read CLAUDE.md, PROJECT_PLAN.md and HANDOFF.md first, then the latest comment on Issue #1.
Setup: `make install && make model` (Python 3.12 via uv). Verify with `make check`.
Continue from "Exact Next Steps" in HANDOFF.md, following the stage protocol in CLAUDE.md
(quality gate -> update HANDOFF.md -> conventional commit + tag -> push main --tags -> Issue #1 comment).
Always run `az account show` and confirm "Azure for Students" before any cloud action.
```
