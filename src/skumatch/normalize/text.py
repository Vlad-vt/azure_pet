"""Text normalisation shared by ingestion and query time.

The same function is applied to catalog rows and invoice lines, so any lossy folding
(``ä``/``ae`` → ``a``) is symmetric and cannot hurt matching.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from skumatch.normalize.units import canonicalize_units

_DIGRAPHS: Final = (("ae", "a"), ("oe", "o"), ("ue", "u"))
_TRANSLATE: Final = str.maketrans({"ß": "ss", "ä": "a", "ö": "o", "ü": "u", "&": " "})
_PUNCT_RE: Final = re.compile(r"[^\w\s.,%]+", re.UNICODE)
_SPACE_RE: Final = re.compile(r"\s+")
# OCR repair is token based: numeric-looking tokens get letters mapped to digits
# ("O,5L" -> "0,5l"), alphabetic tokens get digits mapped to letters ("C0CA" -> "coca").
_NUMERIC_TOKEN: Final = re.compile(r"([\doli|.,x*]+?)(mg|kg|g|ml|cl|dl|ltr|lt|l|%)?")
_MULTIPACK_TOKEN: Final = re.compile(r"\d+er")
_TO_DIGIT: Final = str.maketrans({"o": "0", "l": "1", "i": "1", "|": "1"})
_TO_LETTER: Final = str.maketrans({"0": "o", "1": "l", "|": "l"})
# Decimal separators between digits are kept, others become spaces.
_STRAY_DOT_RE: Final = re.compile(r"(?<!\d)[.,]|[.,](?!\d)")
_ARTICLE_NO_RE: Final = re.compile(
    r"\b(?:art(?:ikel)?\.?\s*-?\s*nr\.?|art\.?|sku|ean|pzn|nr\.?)\s*[:#]?\s*\d{4,14}\b"
)
_LONG_NUMBER_RE: Final = re.compile(r"\b\d{6,14}\b")
_DECIMAL_COMMA_RE: Final = re.compile(r"(?<=\d),(?=\d)")


def fold_text(text: str) -> str:
    """Lowercase, strip accents, fold German umlauts and transliterations."""
    s = unicodedata.normalize("NFKC", text).lower().translate(_TRANSLATE)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    for src, dst in _DIGRAPHS:
        s = s.replace(src, dst)
    return s


def _repair_token(token: str) -> str:
    m = _NUMERIC_TOKEN.fullmatch(token)
    if m and any(c.isdigit() for c in m.group(1)):
        return m.group(1).translate(_TO_DIGIT) + (m.group(2) or "")
    if _MULTIPACK_TOKEN.fullmatch(token):
        return token
    letters = sum(c.isalpha() for c in token)
    digits = sum(c in "01|" for c in token)
    if letters >= 2 and digits and letters > digits:
        return token.translate(_TO_LETTER)
    return token


def repair_ocr(text: str) -> str:
    """Fix common OCR confusions (0/O, 1/l/I) per whitespace-separated token."""
    return " ".join(_repair_token(t) for t in text.split())


def normalize_for_search(text: str) -> str:
    """Canonical form used for FTS and trigram matching."""
    s = fold_text(text)
    s = _ARTICLE_NO_RE.sub(" ", s)
    s = _LONG_NUMBER_RE.sub(" ", s)
    s = repair_ocr(_PUNCT_RE.sub(" ", s))
    s = _DECIMAL_COMMA_RE.sub(".", canonicalize_units(s))
    s = _STRAY_DOT_RE.sub(" ", s)
    return _SPACE_RE.sub(" ", s).strip()


def normalize_for_embedding(text: str) -> str:
    """Light normalisation for the dense model: keep casing/umlauts, unify units and noise."""
    s = unicodedata.normalize("NFKC", text)
    s = _ARTICLE_NO_RE.sub(" ", s.lower())
    s = _LONG_NUMBER_RE.sub(" ", s)
    s = repair_ocr(s.replace("-", " "))
    s = _DECIMAL_COMMA_RE.sub(".", canonicalize_units(s))
    return _SPACE_RE.sub(" ", s).strip()
