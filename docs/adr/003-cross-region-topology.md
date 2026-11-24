# ADR-003: Cross-region topology (API in Switzerland North, database in Denmark East)

- **Status:** Accepted (temporary — revisit when PostgreSQL is unblocked in Germany West Central)
- **Date:** 2026-11-24
- **Context tags:** cost, latency, platform constraints

## Context

The plan was to co-locate Azure Container Apps and PostgreSQL Flexible Server (Burstable B1ms) in
`germanywestcentral`. The Azure for Students subscription made that impossible:

1. An **Allowed resource deployment regions** policy restricts resources to `norwayeast`,
   `denmarkeast`, `germanywestcentral`, `belgiumcentral` and `switzerlandnorth`.
2. PostgreSQL B1ms provisioning results on 2026-11-24:

| Region | PostgreSQL B1ms | Container Apps |
|---|---|---|
| germanywestcentral | ❌ "Provisioning is restricted in this region" | ✅ |
| belgiumcentral | ❌ `RegionalAllocationFailed` (no capacity) | ✅ |
| norwayeast | ❌ `CapacityNotAvailable` | ✅ |
| switzerlandnorth | ❌ `SkuNotAvailable` (despite `list-skus`) | ✅ |
| denmarkeast | ✅ created | ❌ not offered |

3. New Container Apps environments in `switzerlandnorth` default to `environmentMode: Express`,
   which rejects Container Apps Jobs (our migration gate). The environment is pinned to
   `WorkloadProfiles` (preview API `2025-10-02-preview`).

## Decision

- Container Apps environment, API and jobs: **`switzerlandnorth`** (`rg-skumatch-chn`).
- PostgreSQL B1ms: **`denmarkeast`** (Bicep parameter `pgLocation`).
- Minimise round-trips, because every round-trip pays the Zurich ↔ Copenhagen RTT:
  1. the retrieval SQL joins the SKU columns (one statement instead of two);
  2. `hnsw.ef_search` and `pg_trgm.similarity_threshold` are pinned per connection
     (`server_settings`), and matches run in `AUTOCOMMIT`: no `BEGIN` / `SET LOCAL` / `COMMIT`;
  3. `pool_pre_ping` is off on Azure; a read-only match is retried once when SQLAlchemy reports an
     invalidated connection (covered by an integration test that terminates pooled backends).

## Measured impact (live, 100 test lines, warm, sequential)

| Version | Server p50 | Server p95 | DB p50 | Client e2e p50* |
|---|---|---|---|---|
| Initial (≈ 7 round-trips) | 195.8 ms | 229.4 ms | 188.9 ms | 326.9 ms |
| Joined SQL + pinned GUCs + autocommit | 99.7 ms | 120.8 ms | 90.3 ms | 229.8 ms |
| + no pre-ping, retry on drop | **50.7 ms** | **82.7 ms** | **40.6 ms** | 179.2 ms |

\* client measured from the cloud dev container (outside Azure), so it includes ~130 ms of
internet RTT to the ingress.

Live R@1 on the same 100 lines: 0.94 in all three versions.

## Consequences

- ✅ The service runs within budget on the only regions this subscription allows.
- ✅ The round-trip work also helps co-located deployments and PgBouncer users (the transaction
  path remains for PgBouncer and per-request GUC overrides).
- ⚠️ Cross-region traffic: ~30–40 ms of each request is network. Data-transfer charges between
  EU regions are negligible at demo volume (< 1 GB/month).
- 🔁 To co-locate: open an Azure Support request (*Service and subscription limits*) to lift the
  PostgreSQL restriction in `germanywestcentral`, then redeploy with `LOCATION=germanywestcentral`
  and no `PG_LOCATION`.
