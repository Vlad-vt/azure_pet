from __future__ import annotations

from collections import Counter

import pytest

from skumatch.data.synth import (
    SLICES,
    CatalogItem,
    InvoiceLineGenerator,
    find_sibling_pairs,
    render_quantity,
)
from skumatch.normalize import parse_quantity


def _catalog() -> list[CatalogItem]:
    base = [
        ("Milsani", "Frische Vollmilch 3,5%", "1 l", 1, 1000.0, "ml", "whole milks"),
        ("Milsani", "Frische Vollmilch 1,5%", "1 l", 1, 1000.0, "ml", "whole milks"),
        ("Coca-Cola", "Coca-Cola Zero", "6 x 0,33 l", 6, 330.0, "ml", "colas"),
        ("Coca-Cola", "Coca-Cola Classic", "6 x 0,33 l", 6, 330.0, "ml", "colas"),
        ("Haribo", "Goldbären", "200 g", 1, 200.0, "g", "gummies"),
        ("Haribo", "Goldbären", "1 kg", 1, 1000.0, "g", "gummies"),
        ("Müller", "Müllermilch Schokolade", "400 ml", 1, 400.0, "ml", "flavoured milks"),
        ("Dr. Oetker", "Ristorante Pizza Salame", "320 g", 1, 320.0, "g", "pizzas"),
        ("Ritter Sport", "Vollmilch Schokolade", "100 g", 1, 100.0, "g", "milk chocolates"),
        ("Bahlsen", "Leibniz Butterkeks", "200 g", 1, 200.0, "g", "biscuits"),
    ]
    return [
        CatalogItem(i, name, brand, qraw, cnt, amt, unit, cat)
        for i, (brand, name, qraw, cnt, amt, unit, cat) in enumerate(base, start=1)
    ]


def test_generator_is_deterministic() -> None:
    a = InvoiceLineGenerator(_catalog(), seed=42).generate(n_per_slice=8)
    b = InvoiceLineGenerator(_catalog(), seed=42).generate(n_per_slice=8)
    assert [x.to_dict() for x in a] == [x.to_dict() for x in b]
    c = InvoiceLineGenerator(_catalog(), seed=7).generate(n_per_slice=8)
    assert [x.invoice_line for x in a] != [x.invoice_line for x in c]


def test_all_slices_present_and_labelled() -> None:
    lines = InvoiceLineGenerator(_catalog(), seed=42).generate(n_per_slice=5)
    counts = Counter(x.slice for x in lines)
    assert set(counts) == set(SLICES)
    ids = {c.sku_id for c in _catalog()}
    for x in lines:
        assert x.sku_id in ids
        assert x.split in {"dev", "test"}
        assert x.invoice_line.strip()
        assert x.transforms
    assert len({x.id for x in lines}) == len(lines)


def test_hard_negatives_reference_sibling_of_same_brand() -> None:
    cat = {c.sku_id: c for c in _catalog()}
    lines = InvoiceLineGenerator(_catalog(), seed=42).generate(n_per_slice=10)
    hard = [x for x in lines if x.slice == "hard_negatives"]
    assert hard
    for x in hard:
        assert x.hard_negative_sku_id is not None
        assert x.hard_negative_sku_id != x.sku_id
        assert cat[x.sku_id].brand == cat[x.hard_negative_sku_id].brand


def test_hard_negative_keeps_discriminating_token() -> None:
    lines = InvoiceLineGenerator(_catalog(), seed=42).generate(n_per_slice=10)
    for x in lines:
        if x.slice == "hard_negatives" and x.sku_id == 1:
            assert "3,5%" in x.invoice_line


def test_unit_swap_preserves_quantity_semantics() -> None:
    cat = {c.sku_id: c for c in _catalog()}
    lines = InvoiceLineGenerator(_catalog(), seed=42).generate(n_per_slice=10)
    for x in lines:
        if x.slice != "unit_swap":
            continue
        item = cat[x.sku_id]
        q = parse_quantity(x.invoice_line.replace(item.name, "").replace(item.name.upper(), ""))
        assert q is not None
        assert q.unit == item.qty_unit
        assert q.total == pytest.approx(item.qty_count * item.qty_amount, rel=0.01)


def test_render_quantity_avoids_original_form() -> None:
    import random

    item = _catalog()[4]  # 200 g
    rng = random.Random(0)
    for _ in range(20):
        assert render_quantity(item, rng, avoid="200 g").replace(" ", "").lower() != "200g"


def test_find_sibling_pairs() -> None:
    pairs = dict(find_sibling_pairs(_catalog()))
    assert pairs[1] == 2 and pairs[2] == 1  # 3,5% vs 1,5%
    assert pairs[5] == 6  # 200 g vs 1 kg
    assert 8 not in pairs  # unique pizza
