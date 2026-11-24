# Project Plan — Hybrid SKU & Invoice Semantic Matching Service

## Problem
Supplier invoices reference products with noisy, abbreviated, OCR-damaged text
(`MLKRSCH VOLLM 3,5% 1L`, `C0CA C0LA 6x0,33`). Accounts-payable automation needs to map each
invoice line to the canonical SKU in a product catalog. Pure lexical search fails on paraphrase
and unit rewrites; pure dense retrieval fails on exact attributes (fat %, size, flavour).
This service fuses both with **Reciprocal Rank Fusion** inside a single PostgreSQL 16 instance.

## Architecture (target)
- FastAPI + SQLAlchemy 2.0 async + asyncpg on Azure Container Apps (Consumption, scale-to-zero).
- PostgreSQL 16 Flexible Server (Burstable B1ms) with `pgvector` (HNSW, cosine),
  `tsvector` + GIN (FTS, `simple` config + unaccent-style folding), `pg_trgm` + GIN.
- CPU-only INT8 ONNX `intfloat/multilingual-e5-small` (384-d), baked into the image.
- Unit normalisation (`kg/g`, `l/ml/cl`, multipacks `6 x 0,33l` ↔ `6er 330ml`).
- CI/CD: GitHub Actions + OIDC → ghcr.io → Alembic migration gate → ACA revision → smoke test.
- K8s-ready Helm chart (Deployment, Service, PgBouncer, probes, HPA) — linted, not deployed.

## Stages
| Stage | Tag | Deliverables |
|---|---|---|
| 0 Cleanup & Bootstrap | `v0.0-bootstrap` | Azure RG cleanup, repo skeleton, tooling, Issue #1 |
| 1 Data & Synthetic Benchmark | `v0.1-data` | OFF DE/EU catalog (5–10k), seed=42 generator, 1000+ labelled pairs, 4 slices, data report |
| 2 DB, Indexes & ONNX Ingestion | `v0.2-db-ingest` | Models, Alembic (HNSW/GIN/GIN-trgm), ONNX embedder, batch ingest, EXPLAIN ANALYZE |
| 3 Hybrid RRF Engine & API | `v0.3-hybrid-api` | `/v1/match`, `/v1/match/batch`, `/v1/skus/{id}`, `/healthz`, `/readyz`, integration tests |
| 4 Evaluation Suite | `v0.4-eval` | Dense vs Lexical vs Hybrid, R@1/5/10, MRR, NDCG@10, p50/p95, MLflow, significance tests |
| 5 Azure IaC, Helm & ADRs | `v0.5-infra` | Bicep, ACA + PG B1ms deploy, cloud ingest, Helm chart, ADR-001/002 |
| 6 OIDC CI/CD & Polish | `v1.0-release` | Federated creds, ci/deploy/db-power workflows, live smoke test, README + cost analysis |

## Success criteria
- Hybrid RRF beats both single retrievers on `hard_negatives` and `ocr_typos` (paired bootstrap, p < 0.05).
- p95 single-match latency on 0.5 vCPU < 150 ms (warm).
- Image + model fit in 1.5 GiB RAM; cold start does not download the model.
- Monthly Azure cost ≤ $5 at idle.
