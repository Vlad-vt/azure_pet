# CLAUDE.md — working rules for AI agents in this repository

## Language
- Code, commits, README, ADRs, `HANDOFF.md`, GitHub Issue comments: **English only**.

## Budget guardrails (Azure for Students, target $0–5/month)
- Always run `az account show` first and confirm the subscription is **Azure for Students**. Stop and ask otherwise.
- **Forbidden:** AKS, GPU VMs, Azure Cache for Redis, Azure OpenAI (for steady traffic), PostgreSQL General Purpose / Memory Optimized, paid ACR (Basic+).
- Registry: `ghcr.io` only.
- Compute: Azure Container Apps (Consumption), `0.5 vCPU`, `1.0–1.5 GiB`, **`minReplicas: 0`**, `maxReplicas: 2`.
- Database: PostgreSQL Flexible Server **Burstable `Standard_B1ms`**, 32 GiB, no HA, no geo-backup.
- DB auto-restart protection: `.github/workflows/db-power.yml` stops the server every 5 days; stop it after every demo.
- Log Analytics: 30-day retention, INFO level. Never log request bodies or embedding vectors.

## Secrets
- Never commit passwords, connection strings, keys, `.env`, subscription/tenant/client IDs.
- Use GitHub Secrets/Variables and Container Apps secrets. `.env.example` holds placeholders only.

## Engineering standards
- Python 3.12, FastAPI, SQLAlchemy 2.0 async + asyncpg, Alembic, Pydantic v2, structlog.
- Quality gate before every push: `ruff check .`, `ruff format --check .`, `mypy src` (strict), `pytest`.
- Never push a red build to `main`.
- Conventional Commits (`feat(stage-N): ...`, `fix: ...`, `docs: ...`, `ci: ...`).
- Deterministic data: every generator takes `seed=42`.

## Stage protocol (end of every stage)
1. Run the quality gate.
2. Update `HANDOFF.md` (fixed structure: Current Stage & Last Tag, Completed Deliverables,
   Verified Metrics & Commands, Azure Resources State, Known Issues / Decisions,
   Exact Next Steps + "Quick Resume Prompt for Another Device").
3. Commit, tag (`v0.0-bootstrap`, `v0.1-data`, `v0.2-db-ingest`, `v0.3-hybrid-api`,
   `v0.4-eval`, `v0.5-infra`, `v1.0-release`), push `main` with tags.
4. Comment a stage report on GitHub Issue #1 (`Execution Log & Cross-Device Handoff`).

## Useful commands
```bash
make install       # venv + deps
make up            # pgvector + pgbouncer (docker)
make model data    # ONNX model + Open Food Facts catalog + synthetic benchmark
make ingest        # migrations + embeddings + load
make serve         # API on :8000
make eval          # benchmark + MLflow + docs/eval_report.md
make check         # lint + typecheck + tests
```
