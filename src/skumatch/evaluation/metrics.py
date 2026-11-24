"""Ranking metrics for single-relevant-item retrieval and paired significance tests."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


def rank_of(ranking: Sequence[int], relevant: int) -> int | None:
    """1-based position of ``relevant`` in ``ranking`` (None if absent)."""
    for i, item in enumerate(ranking, start=1):
        if item == relevant:
            return i
    return None


def recall_at(rank: int | None, k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def reciprocal_rank(rank: int | None, cutoff: int = 10) -> float:
    return 1.0 / rank if rank is not None and rank <= cutoff else 0.0


def ndcg_at(rank: int | None, k: int = 10) -> float:
    """Single relevant item: IDCG = 1, DCG = 1 / log2(rank + 1)."""
    return 1.0 / math.log2(rank + 1) if rank is not None and rank <= k else 0.0


METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")


def per_query_metrics(rank: int | None) -> dict[str, float]:
    return {
        "recall@1": recall_at(rank, 1),
        "recall@5": recall_at(rank, 5),
        "recall@10": recall_at(rank, 10),
        "mrr@10": reciprocal_rank(rank, 10),
        "ndcg@10": ndcg_at(rank, 10),
    }


def aggregate(ranks: Sequence[int | None]) -> dict[str, float]:
    if not ranks:
        return dict.fromkeys(METRICS, 0.0)
    rows = [per_query_metrics(r) for r in ranks]
    return {m: float(np.mean([row[m] for row in rows])) for m in METRICS}


@dataclass(frozen=True, slots=True)
class PairedTest:
    metric: str
    mean_a: float
    mean_b: float
    delta: float
    ci_low: float
    ci_high: float
    p_bootstrap: float  # one-sided H1: a > b
    p_sign: float | None  # exact one-sided sign test on discordant pairs (binary metrics)
    n: int

    @property
    def significant(self) -> bool:
        return self.p_bootstrap < 0.05 and (self.p_sign is None or self.p_sign < 0.05)


def paired_bootstrap(
    a: npt.ArrayLike,
    b: npt.ArrayLike,
    metric: str,
    *,
    n_resamples: int = 10_000,
    seed: int = 42,
) -> PairedTest:
    """Paired bootstrap of mean(a - b) with a one-sided p-value for ``a > b``."""
    xa = np.asarray(a, dtype=np.float64)
    xb = np.asarray(b, dtype=np.float64)
    if xa.shape != xb.shape or xa.ndim != 1 or xa.size == 0:
        raise ValueError("a and b must be equal-length non-empty 1-D arrays")
    diff = xa - xb
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, diff.size, size=(n_resamples, diff.size))
    means = diff[idx].mean(axis=1)
    p_boot = float((np.sum(means <= 0) + 1) / (n_resamples + 1))
    p_sign: float | None = None
    if set(np.unique(np.concatenate([xa, xb]))) <= {0.0, 1.0}:
        wins = int(np.sum((xa == 1) & (xb == 0)))
        losses = int(np.sum((xa == 0) & (xb == 1)))
        p_sign = sign_test_one_sided(wins, losses)
    return PairedTest(
        metric=metric,
        mean_a=float(xa.mean()),
        mean_b=float(xb.mean()),
        delta=float(diff.mean()),
        ci_low=float(np.percentile(means, 2.5)),
        ci_high=float(np.percentile(means, 97.5)),
        p_bootstrap=p_boot,
        p_sign=p_sign,
        n=int(diff.size),
    )


def sign_test_one_sided(wins: int, losses: int) -> float:
    """P(X >= wins) for X ~ Binomial(wins + losses, 0.5) — exact McNemar, one-sided."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(wins, n + 1))
    return float(tail / 2**n)


def percentile(values: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else 0.0
