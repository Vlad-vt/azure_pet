from __future__ import annotations

import math

import numpy as np
import pytest

from skumatch.evaluation.metrics import (
    aggregate,
    ndcg_at,
    paired_bootstrap,
    rank_of,
    reciprocal_rank,
    sign_test_one_sided,
)


def test_rank_of() -> None:
    assert rank_of([5, 3, 9], 3) == 2
    assert rank_of([5, 3, 9], 7) is None


def test_single_relevant_metrics() -> None:
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(4) == 0.25
    assert reciprocal_rank(11) == 0.0
    assert ndcg_at(1) == 1.0
    assert ndcg_at(3) == pytest.approx(1 / math.log2(4))
    assert ndcg_at(None) == 0.0


def test_aggregate() -> None:
    agg = aggregate([1, 2, None, 6])
    assert agg["recall@1"] == 0.25
    assert agg["recall@5"] == 0.5
    assert agg["recall@10"] == 0.75
    assert agg["mrr@10"] == pytest.approx((1 + 0.5 + 0 + 1 / 6) / 4)


def test_sign_test() -> None:
    assert sign_test_one_sided(0, 0) == 1.0
    assert sign_test_one_sided(10, 0) == pytest.approx(1 / 1024)
    assert sign_test_one_sided(5, 5) > 0.5


def test_paired_bootstrap_detects_improvement() -> None:
    rng = np.random.default_rng(0)
    b = (rng.random(400) < 0.6).astype(float)
    a = np.maximum(b, (rng.random(400) < 0.25).astype(float))  # a dominates b
    res = paired_bootstrap(a, b, "recall@1")
    assert res.delta > 0 and res.ci_low > 0
    assert res.significant


def test_paired_bootstrap_no_difference() -> None:
    x = np.array([1.0, 0.0] * 50)
    res = paired_bootstrap(x, x, "recall@1")
    assert res.delta == 0 and not res.significant


def test_paired_bootstrap_validates_shapes() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap([1.0], [1.0, 0.0], "m")
