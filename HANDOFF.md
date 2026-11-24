# HANDOFF — Hybrid SKU & Invoice Semantic Matching Service

> Single source of truth for resuming work on any device. Updated at the end of every stage.
> Execution log: GitHub Issue #1 (`Execution Log & Cross-Device Handoff`).

## Current Stage & Last Tag
- **Current stage:** Stage 0 — Cleanup & Bootstrap (repository part complete; Azure cleanup pending login)
- **Last tag:** `v0.0-bootstrap`

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

## Verified Metrics & Commands
```text
ruff check .        -> All checks passed
mypy src (strict)   -> Success: no issues found
pytest tests/unit   -> 3 passed (bootstrap)
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

## Exact Next Steps
1. Complete `az login`, verify the subscription is *Azure for Students*, list and delete old RGs,
   purge soft-deleted Key Vaults / Cognitive Services accounts.
2. Stage 1: Open Food Facts DE catalog (`scripts/fetch_off.py`) + seed=42 generator → `v0.1-data`.

### Quick Resume Prompt for Another Device
```text
You are continuing the "Hybrid SKU & Invoice Semantic Matching Service" in repo Vlad-vt/azure_pet.
Read CLAUDE.md, PROJECT_PLAN.md and HANDOFF.md first, then the latest comment on Issue #1.
Setup: `make install && make model` (Python 3.12 via uv). Verify with `make check`.
Continue from "Exact Next Steps" in HANDOFF.md, following the stage protocol in CLAUDE.md
(quality gate -> update HANDOFF.md -> conventional commit + tag -> push main --tags -> Issue #1 comment).
Always run `az account show` and confirm "Azure for Students" before any cloud action.
```
