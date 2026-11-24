# ADR-002: Azure Container Apps (Consumption) vs AKS — total cost of ownership

- **Status:** Accepted
- **Date:** 2026-11-24
- **Context tags:** cost, operations, portability

## Context

The workload is one stateless HTTP API (FastAPI + INT8 ONNX model, ~540 MB RSS; 0.5 vCPU serves
~30–90 rps), bursty and mostly idle (portfolio demo, occasional batch matching). Budget:
**$0–5/month** on an Azure for Students subscription ($100 credit). We still want a credible path
to Kubernetes for teams that run AKS/EKS/GKE.

## Options and monthly cost (Germany West Central list prices, USD, rounded, Nov 2026)

| Item | ACA Consumption (chosen) | AKS Free tier, smallest sensible | AKS Standard tier |
|---|---|---|---|
| Control plane | $0 | $0 (no SLA) | ≈ $73 |
| Compute at idle | **$0** (scale to zero) | 1 × B2s node ≈ $35–40 (system pool cannot scale to 0) | 2 × D2s_v5 ≈ $160 |
| Compute for demo traffic (≈ 20 active h/month at 0.5 vCPU / 1 GiB) | ≈ $0 — within the monthly free grant (180k vCPU-s, 360k GiB-s, 2M requests) | included above | included above |
| Load balancer / public IP | $0 (built-in ingress, managed TLS) | Standard LB + IP ≈ $20 | ≈ $20 |
| Container registry | $0 (ghcr.io) | $0 (ghcr.io) | $0 |
| Logs | Log Analytics, 30 d, 0.15 GB/day cap ≈ $0–2 | Container Insights ≈ $5–15 | ≈ $10–30 |
| Ops effort (upgrades, node images, ingress controller, cert-manager) | ~0 h | 2–4 h/month | 4–8 h/month |
| **Total infrastructure** | **≈ $0–2** | **≈ $60–75** | **≈ $260+** |

PostgreSQL (B1ms, stopped when idle via `db-power.yml`) is the same in every option and excluded.

## Decision

Run on **Azure Container Apps (Consumption)**: `0.5 vCPU / 1 GiB`, `minReplicas: 0`,
`maxReplicas: 2`, HTTP-concurrency scaling, single-revision mode with readiness-gated rollout,
and Alembic migrations as a **Container Apps Job** that gates every deploy.

Stay **Kubernetes-ready without paying for a cluster**: the Helm chart in `infra/helm/skumatch`
(Deployment, Service, HPA, PDB, PgBouncer, pre-upgrade migration hook, restricted pod security)
is linted and rendered in CI (`helm lint --strict`, `helm template`).

## Consequences

- ✅ Idle cost ≈ $0; cost follows real requests; no cluster to patch.
- ✅ Zero-downtime revisions and managed TLS ingress out of the box.
- ⚠️ Cold start after scale-to-zero: container start + ONNX model load ≈ 3–6 s (the model is baked
  into the image, nothing is downloaded). Fine for a demo; `minReplicas: 1` (≈ $8–12/month at
  0.5 vCPU) if a latency SLO is ever required.
- ⚠️ Less control (no DaemonSets, custom CNI or node tuning) — not needed for this workload.
- 🔁 Exit path: the same image + Helm chart deploy to AKS/EKS/GKE; ADR-001 explains why PgBouncer
  becomes worthwhile there. Re-evaluate when steady traffic exceeds ~2M requests/month or more
  than 4 replicas are needed continuously (break-even with a one-node AKS cluster).
