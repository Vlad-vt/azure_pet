"""Unit-of-measure parsing and canonicalisation.

All masses are converted to grams, volumes to millilitres, so ``0,5 kg`` == ``500 g`` and
``6 x 0,33 l`` == ``6er 330ml``. Canonical tokens (``500g``, ``6x330ml``) are injected into the
search text so lexical retrievers see identical tokens for equivalent quantities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_UNIT_FACTORS: Final[dict[str, tuple[str, float]]] = {
    "mg": ("g", 0.001),
    "g": ("g", 1.0),
    "gr": ("g", 1.0),
    "grm": ("g", 1.0),
    "gramm": ("g", 1.0),
    "kg": ("g", 1000.0),
    "kilo": ("g", 1000.0),
    "ml": ("ml", 1.0),
    "cl": ("ml", 10.0),
    "dl": ("ml", 100.0),
    "l": ("ml", 1000.0),
    "lt": ("ml", 1000.0),
    "ltr": ("ml", 1000.0),
    "liter": ("ml", 1000.0),
    "litre": ("ml", 1000.0),
    "stk": ("pc", 1.0),
    "stück": ("pc", 1.0),
    "stueck": ("pc", 1.0),
    "st": ("pc", 1.0),
    "pcs": ("pc", 1.0),
    "pc": ("pc", 1.0),
}

_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(mg|kg|kilo|gramm|grm|gr|g|ml|cl|dl|liter|litre|ltr|lt|l|stück|stueck|stk|pcs|pc|st)"
# "6 x 0,33 l", "6x330ml", "6er 330ml", "6er-pack 0,33l", "4 * 125 g"
_MULTI_RE: Final = re.compile(
    rf"(?<![\w.,])(\d{{1,3}})\s*(?:x|\*|×|er(?:[\s-]*(?:pack|pck|pk))?)\s*{_NUM}\s*{_UNIT}(?![a-zäöü])",
    re.IGNORECASE,
)
_SINGLE_RE: Final = re.compile(rf"(?<![\w.,]){_NUM}\s*{_UNIT}(?![a-zäöü])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Quantity:
    """A normalised package quantity: ``count`` units of ``amount`` ``unit`` each."""

    count: int
    amount: float
    unit: str  # "g" | "ml" | "pc"

    @property
    def total(self) -> float:
        return self.count * self.amount

    def token(self) -> str:
        amount = _fmt(self.amount)
        base = f"{amount}{self.unit}"
        return base if self.count == 1 else f"{self.count}x{base}"

    def matches(self, other: Quantity, rel_tol: float = 0.02) -> bool:
        # Single "500ml" vs multipack "6x500ml" never match because their totals differ.
        return self.unit == other.unit and abs(self.total - other.total) <= rel_tol * max(
            self.total, other.total
        )


def _fmt(value: float) -> str:
    rounded = round(value, 2)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:g}"


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _convert(amount: float, unit: str) -> tuple[float, str] | None:
    spec = _UNIT_FACTORS.get(unit.lower())
    if spec is None:
        return None
    base, factor = spec
    return amount * factor, base


def parse_quantity(text: str | None) -> Quantity | None:
    """Extract the first package quantity from free text."""
    if not text:
        return None
    m = _MULTI_RE.search(text)
    if m:
        conv = _convert(_to_float(m.group(2)), m.group(3))
        count = int(m.group(1))
        if conv and 1 <= count <= 100 and conv[0] > 0:
            return Quantity(count=count, amount=conv[0], unit=conv[1])
    m = _SINGLE_RE.search(text)
    if m:
        conv = _convert(_to_float(m.group(1)), m.group(2))
        if conv and conv[0] > 0:
            return Quantity(count=1, amount=conv[0], unit=conv[1])
    return None


def canonicalize_units(text: str) -> str:
    """Replace every quantity expression in ``text`` with its canonical token."""

    def _multi(m: re.Match[str]) -> str:
        conv = _convert(_to_float(m.group(2)), m.group(3))
        if not conv:
            return m.group(0)
        return Quantity(int(m.group(1)), conv[0], conv[1]).token()

    def _single(m: re.Match[str]) -> str:
        conv = _convert(_to_float(m.group(1)), m.group(2))
        if not conv:
            return m.group(0)
        return Quantity(1, conv[0], conv[1]).token()

    return _SINGLE_RE.sub(_single, _MULTI_RE.sub(_multi, text))
