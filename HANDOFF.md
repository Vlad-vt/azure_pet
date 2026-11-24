# HANDOFF — Hybrid SKU & Invoice Semantic Matching Service

> Single source of truth for resuming work on any device. Updated at the end of every stage.
> Execution log: GitHub Issue #1 (`Execution Log & Cross-Device Handoff`).

## Current Stage & Last Tag
- **Current stage:** Stage 5 — Azure IaC, Helm & ADRs ✅ (live API verified, DB stopped).
  Next: Stage 6 — OIDC CI/CD & final polish.
- **Last tag:** `v0.5-infra`

| Tag | Commit | Notes |
|---|---|---|
| `v0.0-bootstrap` | `18ced0b` | repo skeleton |
| `v0.1-data` | `0bd95e0` | data + generator |
| `v0.2-db-ingest` | `07042bd` | schema, indexes, ingestion |
| `v0.3-hybrid-api` | `9a09c22` | RRF engine + API |
| `v0.4-eval` | `e4f60fe` | benchmark + MLflow |
| `v0.5-infra` | see `git log --grep "docs(stage-5)"` | Azure deployed + live smoke test |

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
- **Stage 3:** `src/skumatch/retrieval/` — weighted RRF (`k=60`, deterministic tie-break), one
  round-trip `UNION ALL` SQL for dense/FTS/trigram top-k, prefix tsquery builder (injection-safe),
  unit-agreement list (pack size parsed from the line == SKU pack size) as a 4th RRF input,
  modes `hybrid` / `dense` / `lexical`
- `src/skumatch/api/` — FastAPI: `POST /v1/match`, `POST /v1/match/batch`, `GET /v1/skus/{id}`,
  `GET /healthz` (liveness, no DB), `GET /readyz` (DB ping, 3 s timeout → 503); request-id
  middleware, access log without bodies, generic 500 handler
- `Dockerfile` (multi-stage, uv.lock, model baked into a layer, non-root uid 10001), `.dockerignore`
- Tests: `tests/unit/test_fusion.py`, `tests/integration/test_api.py`
- **Stage 4:** `scripts/eval.py` — retrieve once, fuse offline through the production `fuse()`;
  dev-split grid search (200 configs, all retriever weights > 0); test-split metrics per slice
  (R@1/5/10, MRR@10, NDCG@10), ablations, live p50/p95 latency per mode
- `src/skumatch/evaluation/metrics.py` (metrics, paired bootstrap, exact sign test),
  `src/skumatch/evaluation/llm_judge.py` (optional, only with `--llm-judge` + API key)
- MLflow tracking in `mlruns/` (local SQLite + artifacts, git-ignored): parent run + nested run per system
- `docs/eval_report.md`, `docs/eval_notes.md`, `docs/eval_summary.json`, README metrics table
- Data fix `844ad59`: token-set catalog dedup (label noise), generator v2 (harder, more realistic)
- Shipped fusion defaults (dev-tuned): `w_dense=0.5, w_fts=0.25, w_trgm=1.5, w_unit=1.0, k=60`
- **Stage 5 (code complete):** `infra/bicep/main.bicep` (Log Analytics 30 d + 0.15 GB/day cap; ACA
  environment + app 0.5 vCPU/1 GiB, min 0/max 2, startup/liveness/readiness probes; PostgreSQL
  Flexible B1ms 32 GiB, no HA/geo/autogrow, `azure.extensions=VECTOR,PG_TRGM`; `migrate` and
  `ingest` ACA Jobs; DB URL only as an ACA secret) — compiles with zero warnings
- `infra/helm/skumatch` — Deployment, Service, HPA, PDB, PgBouncer, pre-upgrade Alembic hook,
  restricted pod security; `helm lint --strict` clean
- `docs/adr/001-connection-pooling-b1ms.md`, `docs/adr/002-aca-vs-aks-tco.md`
- `infra/scripts/`: `azure_cleanup.sh`, `deploy_infra.sh`, `setup_github_oidc.sh`, `create_budget.sh`
  (shellcheck clean)
- `.github/workflows/`: `ci.yml`, `deploy.yml` (ghcr.io → migration gate job → revision → smoke
  test → restore DB power state; skipped until OIDC vars exist), `db-power.yml` (actionlint clean)
- Final `README.md` (Mermaid architecture, benchmark, API, cost analysis)
- **Stage 5 (deployed):** Azure cleanup, Bicep deploy (`rg-skumatch-chn`), `migrate` + `ingest`
  jobs in the cloud, live smoke test, budget `skumatch-monthly`, `docs/adr/003-cross-region-topology.md`,
  round-trip optimisations (joined SQL, pinned GUCs + autocommit, no pre-ping + retry-on-drop)

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
# Stage 3 (uvicorn, 1 worker, ORT 1 thread, through PgBouncer transaction mode)
POST /v1/match  concurrency 1 -> p50 34.5 ms, p95 52.6 ms, 27 rps
POST /v1/match  concurrency 4 -> p50 45.0 ms, p95 63.7 ms, 87 rps
POST /v1/match/batch (100 lines) -> 1.23 s
runtime venv 396 MB + model 135 MB; process RSS ~540 MB (fits 0.5 vCPU / 1.0 GiB ACA)
pytest (unit + integration) -> 70 passed
# Stage 4 (test split = 911 lines; full table in docs/eval_report.md)
Dense R@1 0.942 | Lexical 0.935 | Hybrid equal-w 0.959 | Hybrid dev-tuned (shipped) 0.969, MRR@10 0.982
Hybrid vs Dense   overall R@1 +0.027 (p<0.001) | ocr_typos +0.035 ✅ | hard_negatives +0.008 (tie)
Hybrid vs Lexical overall R@1 +0.033 (p<0.001) | ocr_typos +0.131 ✅ | hard_negatives +0.021 ✅
Hybrid vs Trigram-only: tie (0.969 vs 0.971, p≈0.85)
Live latency (ORT 1 thread, local PG): dense p95 ~14 ms, lexical ~33 ms, hybrid ~43 ms
pytest -> 77 passed
# Stage 5 (local + GitHub Actions)
bicep build (0.31.92) -> 0 warnings | helm lint --strict -> 0 failures, 9 manifests rendered
GitHub Actions ci (ruff, mypy, pytest vs pgvector/pgvector:pg16, helm, bicep) -> green
# Stage 5 — live Azure (100 test lines, warm, sequential)
job migrate 33 s | job ingest 96 s (8,000 SKUs) | cold start from zero ~27 s
server p50 50.7 ms / p95 82.7 ms (db p50 40.6 ms, embed 6.5 ms) — was 195.8 / 229.4 before ADR-003 fixes
live R@1 = 0.94 | /v1/match/batch (100 lines) 4.6 s | pytest -> 78 passed
budget skumatch-monthly: $30/month, alerts at 16.7 % / 50 % / 100 % (actual) -> Owner role
```

## Azure Resources State
Subscription: **Azure for Students** (verified with `az account show`). Stage 0 cleanup done:
deleted `rg-ai-lab` and `rg-rechnungscheck-dev` (2 Cognitive Services accounts + 1 AI Foundry project) and purged both
soft-deleted Cognitive Services accounts; no soft-deleted Key Vaults existed.

| Resource | Name | Region | State |
|---|---|---|---|
| Resource group | `rg-skumatch-chn` | switzerlandnorth | Succeeded |
| Log Analytics | `skumatch-logs` (30 d, 0.15 GB/day cap) | switzerlandnorth | Succeeded |
| ACA environment | `skumatch-env` (`environmentMode: WorkloadProfiles`, Consumption) | switzerlandnorth | Succeeded |
| Container App | `skumatch-api` (0.5 vCPU / 1 GiB, min 0 / max 2), image `:94fbc89176a1` | switzerlandnorth | Running (scale-to-zero) |
| ACA Jobs | `skumatch-migrate`, `skumatch-ingest` | switzerlandnorth | both Succeeded (2026-11-24) |
| Budget | `skumatch-monthly` ($30; alerts $5/$15/$30 → Owner) | subscription | Active |
| PostgreSQL Flexible | `skumatch-pg-t6ucewwfw43f6` (B1ms, PG 16, 32 GiB, no HA) | **denmarkeast** | **Stopped** |

Public URL (after the real image is deployed):
`https://skumatch-api.lemonisland-f8af8152.switzerlandnorth.azurecontainerapps.io`

Container images: `ghcr.io/vlad-vt/azure_pet:<sha12>` + `:latest`, built by `deploy.yml`.
The package and the repository are **public**.
The PostgreSQL admin password exists only in the Container App secret `database-url` and in
`~/.skumatch/pg_admin_password` on the deploying machine (`deploy_infra.sh` recovers it from the
secret on other machines).

#### Why this topology (region log, 2026-11-24)
The subscription carries an *Allowed resource deployment regions* policy: `norwayeast`,
`denmarkeast`, `germanywestcentral`, `belgiumcentral`, `switzerlandnorth`.

| Region | PostgreSQL B1ms | Container Apps |
|---|---|---|
| germanywestcentral | ❌ provisioning restricted for this subscription | ✅ |
| swedencentral | ❌ blocked by region policy | — |
| belgiumcentral | ❌ `RegionalAllocationFailed` (no capacity) | ✅ |
| norwayeast | ❌ `CapacityNotAvailable` | ✅ |
| switzerlandnorth | ❌ `SkuNotAvailable` | ✅ (defaults to *Express* mode → no Jobs; pinned to `WorkloadProfiles`) |
| denmarkeast | ✅ **created** | ❌ not offered |

Hence the API runs in `switzerlandnorth` and the database in `denmarkeast`; see
`docs/adr/003-cross-region-topology.md` for the measured latency and round-trip optimisations. Moving both into `germanywestcentral` needs an Azure Support request
(*Service and subscription limits*) to lift the PostgreSQL restriction.

### Budget alerts — manual checklist (if `create_budget.sh` is rejected for the Students offer)
1. Portal → *Cost Management + Billing* → *Cost Management* → *Budgets* → *+ Add* (scope: the
   Azure for Students subscription).
2. Name `skumatch-monthly`, reset period *Monthly*, amount **$30**.
3. Alert conditions (type *Actual*): **16.7 %** (= $5), **50 %** (= $15), **100 %** (= $30);
   recipient: your e-mail. Save.
4. Also check *Azure for Students* credit balance at https://www.microsoftazuresponsorships.com/balance.

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
- Benchmark honesty: v1 saturated; v2 fixed label noise and raised difficulty *before* the
  final comparison. Trigram-only ties Hybrid on this synthetic set (char-level noise); Hybrid
  ships for robustness (see `docs/eval_notes.md`). Hybrid vs Dense on `hard_negatives` is a tie.
- MLflow 3 put the plain file store in maintenance mode; tracking uses `sqlite:///mlruns/mlflow.db`
  (still local and file-based). Browse: `mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db`.
- The cloud agent cannot push git tags (proxy 403) or set GitHub secrets (no `gh` write access);
  the repository was made public on 2026-11-24 (history scanned: no IDs, passwords or e-mails);
  both are workstation steps. Tags were *not* worked around via CI on purpose.
- `deploy.yml` builds and pushes the image even before Azure exists; its `release` job is
  *skipped* (not failed) until the `AZURE_RG` variable is set.
- `db-power.yml` runs every 5 days as requested; worst case after Azure's 7-day auto-start is
  ~4 days of B1ms compute (≈ $1.6). A daily schedule would cap it at < 1 day.
- `/healthz` never touches the DB so a stopped database does not crash-loop replicas; `/readyz`
  reports 503 instead. The image cannot be built in the cloud dev container (no Docker daemon);
  the runtime environment was verified with `uv sync --frozen --no-dev --extra data --no-editable`.

## Exact Next Steps
1. ✅ Stage 0 cleanup · ✅ ghcr public · ✅ infra deployed · ✅ migrate/ingest · ✅ smoke test · ✅ budget.
2. Stage 6 — OIDC: create the Entra app + federated credentials (`main`,
   `environment:production`) and a Contributor assignment on `rg-skumatch-chn` (agent can do the
   `az` part). The GitHub secrets/variables must be set by the owner (agent has no `gh` write):
   secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`; variables
   `AZURE_RG=rg-skumatch-chn`, `ACA_APP=skumatch-api`, `ACA_MIGRATE_JOB=skumatch-migrate`,
   `ACA_INGEST_JOB=skumatch-ingest`, `PG_SERVER=skumatch-pg-t6ucewwfw43f6`.
3. Run Actions → deploy (workflow_dispatch) → expect green: migration gate, new revision, smoke
   test, DB restored to Stopped. Then Actions → db-power → `status`.
4. Final README polish, `v1.0-release`; push all tags from a workstation (tag table above).

To demo: `az postgres flexible-server start -g rg-skumatch-chn -n skumatch-pg-t6ucewwfw43f6`
(or Actions → db-power → start), open `/docs`, then stop the DB again.

### Quick Resume Prompt for Another Device
```text
You are continuing the "Hybrid SKU & Invoice Semantic Matching Service" in repo Vlad-vt/azure_pet.
Read CLAUDE.md, PROJECT_PLAN.md and HANDOFF.md first, then the latest comment on Issue #1.
Setup: `make install && make model` (Python 3.12 via uv). Verify with `make check`.
Continue from "Exact Next Steps" in HANDOFF.md, following the stage protocol in CLAUDE.md
(quality gate -> update HANDOFF.md -> conventional commit + tag -> push main --tags -> Issue #1 comment).
Always run `az account show` and confirm "Azure for Students" before any cloud action.
```
