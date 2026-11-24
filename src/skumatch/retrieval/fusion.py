"""Weighted Reciprocal Rank Fusion (Cormack et al., 2009).

``score(d) = Σ_r w_r / (k + rank_r(d))`` with 1-based ranks. Documents missing from a list
contribute nothing for that retriever. Ties are broken by best individual rank, then by id, so
results are deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def reciprocal_rank_fusion(
    ranked_lists: Mapping[str, Sequence[int]],
    weights: Mapping[str, float] | None = None,
    k: int = 60,
) -> list[tuple[int, float]]:
    if k < 1:
        raise ValueError("k must be >= 1")
    scores: dict[int, float] = {}
    best_rank: dict[int, int] = {}
    for name, ids in ranked_lists.items():
        w = 1.0 if weights is None else float(weights.get(name, 0.0))
        if w == 0.0:
            continue
        for rank, doc_id in enumerate(ids, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
            best_rank[doc_id] = min(best_rank.get(doc_id, rank), rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], best_rank[kv[0]], kv[0]))
