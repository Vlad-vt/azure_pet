from __future__ import annotations

import pytest

from skumatch.normalize import Quantity, canonicalize_units, normalize_for_search, parse_quantity
from skumatch.normalize.text import fold_text, normalize_for_embedding, repair_ocr


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500 g", Quantity(1, 500.0, "g")),
        ("0,5 kg", Quantity(1, 500.0, "g")),
        ("1L", Quantity(1, 1000.0, "ml")),
        ("75cl", Quantity(1, 750.0, "ml")),
        ("6 x 0,33 l", Quantity(6, 330.0, "ml")),
        ("6er 330ml", Quantity(6, 330.0, "ml")),
        ("6er-Pack 0,33L", Quantity(6, 330.0, "ml")),
        ("4 * 125 g", Quantity(4, 125.0, "g")),
        ("Bio Vollmilch 3,8% 1 l", Quantity(1, 1000.0, "ml")),
    ],
)
def test_parse_quantity(text: str, expected: Quantity) -> None:
    assert parse_quantity(text) == expected


@pytest.mark.parametrize("text", ["", None, "Vollmilch", "3,5%", "Vitamin B12"])
def test_parse_quantity_none(text: str | None) -> None:
    assert parse_quantity(text) is None


def test_equivalent_quantities_share_token() -> None:
    assert canonicalize_units("0,5 kg") == canonicalize_units("500g") == "500g"
    assert canonicalize_units("6 x 0,33 l") == canonicalize_units("6er 330ml") == "6x330ml"


def test_quantity_matches_with_tolerance() -> None:
    assert Quantity(1, 500, "g").matches(Quantity(1, 505, "g"))
    assert not Quantity(1, 500, "g").matches(Quantity(1, 500, "ml"))
    assert not Quantity(1, 330, "ml").matches(Quantity(6, 330, "ml"))


def test_fold_text_is_symmetric_for_umlaut_spellings() -> None:
    assert fold_text("Käse") == fold_text("Kaese") == fold_text("KASE")
    assert fold_text("Weißbier") == fold_text("WEISSBIER")


@pytest.mark.parametrize(
    ("raw", "fixed"),
    [
        ("c0ca c0la", "coca cola"),
        ("mi1ch", "milch"),
        ("o,5l", "0,5l"),
        ("l,5", "1,5"),
        ("10er", "10er"),
    ],
)
def test_repair_ocr(raw: str, fixed: str) -> None:
    assert repair_ocr(raw) == fixed


def test_normalize_for_search_end_to_end() -> None:
    assert (
        normalize_for_search("C0CA C0LA Zer0 6x0,33L Art.-Nr. 4711023") == "coca cola zero 6x330ml"
    )
    assert normalize_for_search("MÜLLER Käse-Sahne O,5kg") == "muller kase sahne 500g"
    assert normalize_for_search("Milch 3,5% 1l") == normalize_for_search("MILCH 3.5% 1000 ML")
    assert "4001686301265" not in normalize_for_search("Haribo 200g EAN 4001686301265")


def test_normalize_for_embedding_keeps_umlauts() -> None:
    assert normalize_for_embedding("Müller Käse 0,5 kg") == "müller käse 500g"
