from __future__ import annotations

import pytest

from skumatch.retrieval.fusion import reciprocal_rank_fusion
from skumatch.retrieval.sql import build_tsquery, retrieval_sql


def test_rrf_basic_scores() -> None:
    fused = dict(reciprocal_rank_fusion({"a": [1, 2, 3], "b": [3, 1]}, k=60))
    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2] == pytest.approx(1 / 62)


def test_rrf_order_and_consensus() -> None:
    order = [i for i, _ in reciprocal_rank_fusion({"a": [1, 2, 3], "b": [2, 3, 1], "c": [2]})]
    assert order[0] == 2  # ranked well by all three lists


def test_rrf_weights_and_zero_weight() -> None:
    lists = {"dense": [1, 2], "fts": [2, 1]}
    assert reciprocal_rank_fusion(lists, {"dense": 2.0, "fts": 1.0})[0][0] == 1
    assert reciprocal_rank_fusion(lists, {"dense": 0.0, "fts": 1.0})[0][0] == 2
    assert reciprocal_rank_fusion(lists, {"dense": 1.0})[0][0] == 1  # missing weight -> 0


def test_rrf_deterministic_tie_break() -> None:
    # identical scores -> best individual rank, then id
    assert [i for i, _ in reciprocal_rank_fusion({"a": [5, 7], "b": [7, 5]})] == [5, 7]


def test_rrf_rejects_bad_k() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"a": [1]}, k=0)


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion({"a": [], "b": []}) == []


def test_build_tsquery_prefix_and_exact_terms() -> None:
    q = build_tsquery("milsa vollm 3.5% 1000ml milsa x")
    assert q == "'milsa':* | 'vollm':* | '3.5' | '1000ml'"


@pytest.mark.parametrize("hostile", ["a & b", "x' | 'y", "!!", "(foo:*) <-> bar", ""])
def test_build_tsquery_never_emits_operators_from_input(hostile: str) -> None:
    q = build_tsquery(hostile.lower())
    for ch in "&!()<>":
        assert ch not in q


def test_retrieval_sql_allow_list() -> None:
    assert "UNION ALL" in str(retrieval_sql(("dense", "fts", "trgm")))
    with pytest.raises(ValueError):
        retrieval_sql(("dense", "drop table"))
    with pytest.raises(ValueError):
        retrieval_sql(())
