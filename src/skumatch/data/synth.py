"""Deterministic generator of noisy supplier-invoice lines with ground-truth SKU labels.

Four evaluation slices model the failure modes seen in real accounts-payable data:

* ``abbreviations``  – truncated / vowel-stripped words, brand short codes, CAPS, dropped words
* ``unit_swap``      – the same quantity written differently (``500 g`` ↔ ``0,5 kg``,
                       ``6 x 0,33 l`` ↔ ``6er 330ml``)
* ``ocr_typos``      – OCR confusions (``0/O``, ``1/l/I``, ``rn/m``), lost umlauts, ``ß→ss``,
                       stray article numbers and invoice noise tokens
* ``hard_negatives`` – the catalog contains a sibling SKU (same brand, near-identical name) that
                       differs only in fat %, flavour or pack size; the line keeps the
                       discriminating attribute and the sibling id is recorded

All randomness flows through one ``random.Random(seed)`` so output is byte-for-byte reproducible.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Final

from skumatch.normalize.text import fold_text

SLICES: Final = ("abbreviations", "unit_swap", "ocr_typos", "hard_negatives")

_STOPWORDS: Final = frozenset(
    {"mit", "und", "aus", "der", "die", "das", "von", "im", "in", "für", "fur", "a", "la", "le"}
)
_ABBREV: Final[dict[str, str]] = {
    "vollmilch": "VOLLM.",
    "milch": "MI.",
    "schokolade": "SCHOKO",
    "joghurt": "JOGH.",
    "packung": "PCK",
    "flasche": "FL.",
    "mineralwasser": "MIN.WASS.",
    "natur": "NAT.",
    "frischkäse": "FRISCHK.",
    "käse": "KAESE",
    "butter": "BUTT.",
    "erdbeere": "ERDB.",
    "vanille": "VAN.",
    "classic": "CLASS.",
    "original": "ORIG.",
    "laktosefrei": "LF",
    "fettarme": "FETTARM",
    "haltbare": "H-",
    "bio": "BIO",
    "zero": "ZERO",
    "zucker": "ZUCK.",
    "getränk": "GETR.",
    "orangensaft": "O-SAFT",
    "apfelsaft": "A-SAFT",
    "nudeln": "NUD.",
    "tomaten": "TOM.",
    "gurken": "GURK.",
    "kartoffel": "KART.",
    "hähnchen": "HAEHN.",
    "schinken": "SCHINK.",
    "salami": "SAL.",
    "brot": "BR.",
    "vollkorn": "VK",
    "weizen": "WEIZ.",
    "mehl": "MEHL",
    "sahne": "SAH.",
    "quark": "QU.",
    "mineral": "MIN.",
    "kaffee": "KAFF.",
    "bohnen": "BOHN.",
}
_OCR_SUBS: Final[dict[str, tuple[str, ...]]] = {
    "o": ("0",),
    "O": ("0",),
    "0": ("O", "o"),
    "l": ("1", "I", "|"),
    "I": ("l", "1"),
    "i": ("1", "l"),
    "1": ("l", "I"),
    "S": ("5",),
    "s": ("5",),
    "B": ("8",),
    "e": ("c",),
    "a": ("o",),
    "m": ("rn",),
    "n": ("ri",),
    "u": ("v",),
    "ä": ("a", "ae", "a"),
    "ö": ("o", "oe"),
    "ü": ("u", "ue"),
    "Ä": ("A", "AE"),
    "Ö": ("O", "OE"),
    "Ü": ("U", "UE"),
    "ß": ("ss", "B"),
}
_INVOICE_NOISE: Final = ("EUR", "ST", "1 x", "KRT", "MwSt 7%", "Pos.", "*", "VE", "NETTO")
_WORD_RE: Final = re.compile(r"\w[\w'%.,-]*", re.UNICODE)


@dataclass(frozen=True, slots=True)
class CatalogItem:
    sku_id: int
    name: str
    brand: str
    quantity_raw: str
    qty_count: int
    qty_amount: float
    qty_unit: str
    category: str


@dataclass(slots=True)
class LabelledLine:
    id: str
    invoice_line: str
    sku_id: int
    slice: str
    split: str
    hard_negative_sku_id: int | None = None
    transforms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _num(value: float, comma: bool = True, max_decimals: int = 3) -> str:
    text = f"{value:.{max_decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if comma else text


def display_name(item: CatalogItem) -> str:
    """Brand + name, without repeating the brand when the name already starts with it."""
    if fold_text(item.name).startswith(fold_text(item.brand)):
        return item.name
    return f"{item.brand} {item.name}"


def render_quantity(item: CatalogItem, rng: random.Random, avoid: str | None = None) -> str:
    """Render the item's quantity in a randomly chosen but equivalent textual form."""
    options = _quantity_variants(item)
    avoid_key = _qkey(avoid) if avoid else None
    filtered = [o for o in options if _qkey(o) != avoid_key] or options
    return rng.choice(filtered)


def _qkey(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _quantity_variants(item: CatalogItem) -> list[str]:
    amount, unit, count = item.qty_amount, item.qty_unit, item.qty_count
    singles: list[str] = []
    if unit == "g":
        singles += [f"{_num(amount)} g", f"{_num(amount)}g", f"{_num(amount)} GR"]
        if amount >= 100:
            singles += [f"{_num(amount / 1000)} kg", f"{_num(amount / 1000)}KG"]
    elif unit == "ml":
        singles += [f"{_num(amount)} ml", f"{_num(amount)}ML"]
        if amount >= 100:
            singles += [
                f"{_num(amount / 1000)} l",
                f"{_num(amount / 1000)}L",
                f"{_num(amount / 1000)} LTR",
            ]
        if amount >= 10 and amount % 10 == 0:
            singles += [f"{_num(amount / 10)} cl"]
    else:
        singles += [f"{_num(amount)} Stk"]
    if count == 1:
        return singles
    multi: list[str] = []
    for s in singles:
        compact = s.replace(" ", "")
        multi += [
            f"{count} x {s}",
            f"{count}x{compact}",
            f"{count}er {compact}",
            f"{count}er-Pack {s}",
        ]
    return multi


class InvoiceLineGenerator:
    def __init__(self, catalog: Sequence[CatalogItem], seed: int = 42) -> None:
        if not catalog:
            raise ValueError("catalog must not be empty")
        self.catalog = list(catalog)
        self.by_id = {c.sku_id: c for c in self.catalog}
        self.seed = seed
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------ public API
    def generate(self, n_per_slice: int = 300, dev_fraction: float = 0.2) -> list[LabelledLine]:
        lines: list[LabelledLine] = []
        lines += self._slice("abbreviations", self._abbreviate, n_per_slice)
        lines += self._slice("unit_swap", self._unit_swap, n_per_slice)
        lines += self._slice("ocr_typos", self._ocr, n_per_slice)
        lines += self._hard_negatives(n_per_slice)
        for line in lines:
            line.split = "dev" if self.rng.random() < dev_fraction else "test"
        return lines

    # ------------------------------------------------------------------ slices
    def _slice(
        self,
        name: str,
        fn: object,
        n: int,
    ) -> list[LabelledLine]:
        assert callable(fn)
        items = self.rng.sample(self.catalog, k=min(n, len(self.catalog)))
        out: list[LabelledLine] = []
        for i, item in enumerate(items, start=1):
            text, transforms = fn(item)
            out.append(
                LabelledLine(
                    id=f"{name[:4]}-{i:04d}",
                    invoice_line=text,
                    sku_id=item.sku_id,
                    slice=name,
                    split="",
                    transforms=transforms,
                )
            )
        return out

    def _abbreviate(self, item: CatalogItem) -> tuple[str, list[str]]:
        rng = self.rng
        transforms: list[str] = []
        roll = rng.random()
        if roll < 0.2:
            brand = ""
            transforms.append("brand_omitted")
        elif roll < 0.7:
            brand = self._brand_code(item.brand)
            transforms.append("brand_code")
        else:
            brand = item.brand.upper()
        name = item.name
        if fold_text(name).startswith(fold_text(item.brand)):
            name = name[len(item.brand) :].strip(" -")
        words: list[str] = []
        for w in name.split():
            lw = w.lower()
            if lw in _STOPWORDS and rng.random() < 0.7:
                transforms.append("drop_stopword")
                continue
            if lw in _ABBREV and rng.random() < 0.8:
                words.append(_ABBREV[lw])
                transforms.append("dict_abbrev")
            elif len(w) >= 6 and w.isalpha() and rng.random() < 0.6:
                if rng.random() < 0.5:
                    words.append(w[: rng.randint(3, 5)].upper() + ".")
                    transforms.append("truncate")
                else:
                    words.append(self._consonant_skeleton(w))
                    transforms.append("skeleton")
            else:
                words.append(w.upper())
        if not transforms:
            words = [w[: max(3, len(w) - 2)].upper() + "." if len(w) > 4 else w for w in words]
            transforms.append("truncate")
        qty = (
            item.quantity_raw.upper().replace(" ", "") if rng.random() < 0.5 else item.quantity_raw
        )
        if len(words) >= 3 and rng.random() < 0.2:
            words = words[1:] + words[:1]
            transforms.append("word_rotation")
        head = " ".join([brand, *words]).strip()
        if rng.random() < 0.3 and len(head) > 26:
            head = head[: rng.randint(22, 26)].rstrip()
            transforms.append("field_width_cut")
        return _squash(f"{head} {qty}"), sorted(set(transforms))

    def _unit_swap(self, item: CatalogItem) -> tuple[str, list[str]]:
        rng = self.rng
        qty = render_quantity(item, rng, avoid=item.quantity_raw)
        base = display_name(item)
        if rng.random() < 0.5:
            base = base.upper()
        line = f"{qty} {base}" if rng.random() < 0.3 else f"{base} {qty}"
        transforms = ["unit_rewrite"] + (["qty_first"] if line.startswith(qty) else [])
        return _squash(line), transforms

    def _ocr(self, item: CatalogItem) -> tuple[str, list[str]]:
        rng = self.rng
        transforms: list[str] = []
        base = f"{display_name(item)} {item.quantity_raw}"
        if rng.random() < 0.6:
            base = base.upper()
        chars: list[str] = []
        rate = rng.uniform(0.10, 0.20)
        for c in base:
            if c in "äöüÄÖÜß" and rng.random() < 0.85:
                chars.append(rng.choice(_OCR_SUBS[c]))
                transforms.append("umlaut_loss")
            elif c in _OCR_SUBS and rng.random() < rate:
                chars.append(rng.choice(_OCR_SUBS[c]))
                transforms.append("char_confusion")
            elif c == " " and rng.random() < 0.05:
                transforms.append("merged_tokens")
            elif c.isalpha() and rng.random() < 0.015:
                transforms.append("char_drop")
            else:
                chars.append(c)
        line = "".join(chars)
        if not transforms:
            idx = rng.randrange(len(line))
            line = line[:idx] + line[idx + 1 :]
            transforms.append("char_drop")
        if rng.random() < 0.5:
            line = f"Art.-Nr. {rng.randint(10000, 999999)} {line}"
            transforms.append("article_no")
        if rng.random() < 0.4:
            line = f"{line} {rng.choice(_INVOICE_NOISE)}"
            transforms.append("noise_token")
        return _squash(line), sorted(set(transforms))

    def _hard_negatives(self, n: int) -> list[LabelledLine]:
        pairs = find_sibling_pairs(self.catalog)
        self.rng.shuffle(pairs)
        used: set[int] = set()
        out: list[LabelledLine] = []
        for target_id, negative_id in pairs:
            if target_id in used:
                continue
            used.add(target_id)
            target = self.by_id[target_id]
            negative = self.by_id[negative_id]
            text, transforms = self._hard_negative_line(target, negative)
            out.append(
                LabelledLine(
                    id=f"hard-{len(out) + 1:04d}",
                    invoice_line=text,
                    sku_id=target_id,
                    slice="hard_negatives",
                    split="",
                    hard_negative_sku_id=negative_id,
                    transforms=transforms,
                )
            )
            if len(out) >= n:
                break
        return out

    def _hard_negative_line(
        self, target: CatalogItem, negative: CatalogItem
    ) -> tuple[str, list[str]]:
        """Mild noise only on tokens shared with the sibling; discriminating tokens survive."""
        rng = self.rng
        discriminating = _tokens(target.name) - _tokens(negative.name)
        transforms = ["sibling_in_catalog"]
        words: list[str] = []
        name = target.name
        if fold_text(name).startswith(fold_text(target.brand)):
            name = name[len(target.brand) :].strip(" -")
        if rng.random() < 0.5:
            words.append(self._brand_code(target.brand))
            transforms.append("brand_code")
        else:
            words.append(target.brand.upper())
        for w in name.split():
            key = fold_text(w).strip(".,")
            if key in discriminating:
                words.append(w.upper() if rng.random() < 0.5 else w)
                continue
            if len(w) >= 6 and w.isalpha() and rng.random() < 0.5:
                if rng.random() < 0.5:
                    words.append(w[: rng.randint(3, 5)].upper() + ".")
                    transforms.append("truncate_shared")
                else:
                    words.append(self._consonant_skeleton(w))
                    transforms.append("skeleton_shared")
            else:
                words.append(w.upper() if rng.random() < 0.6 else w)
        if _total(target) != _total(negative) or rng.random() < 0.5:
            qty = render_quantity(target, rng)
            transforms.append("unit_rewrite")
        else:
            qty = target.quantity_raw
        return _squash(" ".join([*words, qty])), sorted(set(transforms))

    # ------------------------------------------------------------------ helpers
    def _brand_code(self, brand: str) -> str:
        parts = [p for p in re.split(r"[\s.\-&]+", brand) if p]
        if len(parts) >= 2 and self.rng.random() < 0.5:
            return "".join(p[0] for p in parts).upper()
        word = parts[0] if parts else brand
        return word[: self.rng.randint(3, 5)].upper()

    def _consonant_skeleton(self, word: str) -> str:
        head, tail = word[0], word[1:]
        skel = head + re.sub(r"[aeiouäöüAEIOUÄÖÜ]", "", tail)
        return skel.upper()


def _tokens(text: str) -> set[str]:
    return {fold_text(t).strip(".,") for t in _WORD_RE.findall(text)} - {""}


def _total(item: CatalogItem) -> float:
    return round(item.qty_count * item.qty_amount, 1)


def _squash(text: str) -> str:
    return " ".join(text.split())


def find_sibling_pairs(
    catalog: Iterable[CatalogItem], min_jaccard: float = 0.5
) -> list[tuple[int, int]]:
    """Pairs (target, sibling) with same brand + category, high name overlap, different SKU."""
    groups: dict[tuple[str, str], list[CatalogItem]] = defaultdict(list)
    for item in catalog:
        groups[(fold_text(item.brand), item.category)].append(item)
    pairs: list[tuple[int, int]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        toks = {m.sku_id: _tokens(m.name) for m in members}
        for a in members:
            best: tuple[float, int] | None = None
            for b in members:
                if a.sku_id == b.sku_id:
                    continue
                ta, tb = toks[a.sku_id], toks[b.sku_id]
                union = ta | tb
                if not union:
                    continue
                jac = len(ta & tb) / len(union)
                # The target must carry its own discriminating evidence: a name token the
                # sibling lacks, or a different pack size. Otherwise the label is ambiguous.
                differs = bool(ta - tb) or _total(a) != _total(b)
                if jac >= min_jaccard and differs and (best is None or jac > best[0]):
                    best = (jac, b.sku_id)
            if best is not None:
                pairs.append((a.sku_id, best[1]))
    pairs.sort()
    return pairs
