# Hybrid SKU & Invoice Semantic Matching Service

Maps noisy supplier-invoice lines (`MILSA. Speisequark MAGERSTUFE 0,25 KG`) to catalog SKUs with
**Reciprocal Rank Fusion** over pgvector (HNSW), PostgreSQL full-text search and `pg_trgm` —
all inside one PostgreSQL 16 instance, CPU-only INT8 ONNX embeddings.

> Work in progress — see `PROJECT_PLAN.md` and `HANDOFF.md`.

## Benchmark (test split, 911 synthetic invoice lines, 8,000 Open Food Facts DE SKUs)

<!-- EVAL:START -->

| System | R@1 | R@5 | R@10 | MRR@10 | NDCG@10 |
|---|---|---|---|---|---|
| Dense (HNSW) | 0.942 | 0.985 | 0.990 | 0.961 | 0.968 |
| Lexical (FTS+Trigram RRF) | 0.935 | 0.992 | 0.999 | 0.960 | 0.970 |
| Hybrid RRF (equal weights) | 0.959 | 0.996 | 0.999 | 0.976 | 0.982 |
| Hybrid RRF (dev-tuned, shipped) | 0.969 | 0.997 | 0.998 | 0.982 | 0.986 |

Per-slice: [`docs/eval_report.md`](docs/eval_report.md).

<!-- EVAL:END -->
