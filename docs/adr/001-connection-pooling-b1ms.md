# ADR-001: Connection pooling on Azure PostgreSQL Flexible Server (Burstable B1ms)

- **Status:** Accepted
- **Date:** 2026-11-24
- **Context tags:** cost, reliability, database

## Context

The service runs on Azure Container Apps (Consumption, `minReplicas: 0`, `maxReplicas: 2`) against
PostgreSQL Flexible Server **Burstable `Standard_B1ms`** (1 vCore, 2 GiB RAM) — the only database
tier compatible with a $0–5/month budget.

Facts that constrain the design:

1. **Built-in PgBouncer is not available on Burstable tiers.** Azure exposes the managed
   PgBouncer (`pgbouncer.enabled`) only on General Purpose / Memory Optimized compute.
2. **B1ms has a low connection ceiling.** `max_connections` defaults to 50 on B1ms, part of which
   Azure reserves for maintenance; each backend costs ~5–10 MB of the 2 GiB.
3. **Workload shape:** one match = one short transaction (`set_config(...)` + a single
   `UNION ALL` query for dense/FTS/trigram + a primary-key lookup, ~5–40 ms DB time).
   Concurrency per replica is bounded by the 0.5 vCPU ONNX embedder (≈ 30–90 rps per replica).
4. **Scale-to-zero:** replicas appear and disappear; connection bursts happen at cold start.
5. Locally and in Kubernetes we *do* run PgBouncer (transaction pooling), so the code must work
   in both modes.

## Decision

On Azure B1ms we **do not deploy a self-hosted PgBouncer**. Every API replica uses a small,
conservative SQLAlchemy async pool:

| Setting | Value | Why |
|---|---|---|
| `pool_size` | 5 | ≥ in-flight DB work a 0.5 vCPU replica can generate |
| `max_overflow` | 5 | absorbs bursts; hard cap 10 per replica |
| `pool_pre_ping` | `True` | survives server stop/start and idle disconnects |
| `pool_recycle` | 1800 s | avoids stale connections across maintenance windows |
| `pool_timeout` | 10 s | fail fast instead of queueing requests indefinitely |
| asyncpg `command_timeout` | 10 s | bounded statement time |

Worst case: `maxReplicas (2) × (5 + 5) = 20` connections + one migration/ingest job (≤ 2) =
**22 of ~50**, leaving headroom for `psql`, Azure maintenance and a third replica.

The code supports both modes behind one flag, `SKUMATCH_DB_PGBOUNCER`:

- `false` (Azure): asyncpg prepared-statement cache enabled, `application_name` startup GUC set,
  TLS on (`SKUMATCH_DB_SSL=true`).
- `true` (docker-compose / Helm): `statement_cache_size=0`, `prepared_statement_cache_size=0`,
  no startup GUCs — required by PgBouncer **transaction** pooling. Per-request GUCs
  (`hnsw.ef_search`, `pg_trgm.similarity_threshold`) use `set_config(..., true)` (transaction
  local), which is safe under transaction pooling.

Alembic migrations always use the **direct** URL (`SKUMATCH_DATABASE_URL_DIRECT`), never a pooler.

## Alternatives considered

| Option | Verdict |
|---|---|
| General Purpose `D2ds_v5` to get the managed PgBouncer | ≈ $130+/month — violates the budget |
| Self-hosted PgBouncer as a second Container App | a TCP proxy must stay warm (no scale-to-zero) ≈ $10–15/month, extra hop, extra TLS/auth config; pays off only beyond ~5 replicas |
| No pool (connect per request) | TLS + SCRAM handshake ≈ 30–60 ms per request to Azure PG; roughly doubles p95 |
| Large pool (20 + 5) | two replicas could exhaust B1ms connections during cold-start bursts |

## Consequences

- ✅ No extra infrastructure cost, lowest latency (no extra hop), simple operations.
- ✅ The same code runs behind PgBouncer in Kubernetes (verified locally: 60 concurrent matches
  through PgBouncer transaction mode).
- ⚠️ Connections scale linearly with replicas. **Revisit** when `maxReplicas > 4` or a second
  service shares the server: deploy PgBouncer (the Helm chart already ships it) or move to a
  tier with the managed pooler.
- ⚠️ Security trade-off: ACA Consumption has no static egress IP, so the server allows Azure
  services (`0.0.0.0` firewall rule) with TLS enforced and a 32+ character random password kept
  only in GitHub Secrets and Container Apps secrets. VNet-integrated ACA + private access to
  PostgreSQL removes this exposure for ≈ $1/month (private DNS zone) and is the first hardening
  step after the portfolio phase.
- Monitoring: alert when the Azure Monitor metric `active_connections` exceeds 35.
