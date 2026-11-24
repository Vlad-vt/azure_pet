"""SQL for the three retrievers, issued as ONE round-trip (UNION ALL of three ranked CTEs).

Each branch is an index-driven top-k:
* dense — ``ORDER BY embedding <=> $vec LIMIT k``          -> HNSW (vector_cosine_ops)
* fts   — ``WHERE search_tsv @@ $tsq ORDER BY ts_rank``    -> GIN (tsvector)
* trgm  — ``WHERE search_text % $q ORDER BY similarity``   -> GIN (gin_trgm_ops)
"""

from __future__ import annotations

import re
from typing import Final

from sqlalchemy import TextClause, text

_TOKEN_RE: Final = re.compile(r"[a-z0-9][a-z0-9.]*")
_MAX_TERMS: Final = 16

SET_LOCALS: Final[TextClause] = text(
    "SELECT set_config('hnsw.ef_search', :ef_search, true), "
    "set_config('pg_trgm.similarity_threshold', :trgm_threshold, true)"
)

_DENSE: Final = """
dense AS (
    SELECT id, 'dense'::text AS retriever,
           row_number() OVER (ORDER BY dist, id) AS rnk, 1 - dist AS score
    FROM (
        SELECT id, embedding <=> CAST(:vec AS vector) AS dist
        FROM skus ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k
    ) d
)"""
_FTS: Final = """
fts AS (
    SELECT id, 'fts'::text AS retriever,
           row_number() OVER (ORDER BY score DESC, id) AS rnk, score
    FROM (
        SELECT s.id, ts_rank_cd(s.search_tsv, q.query, 1) AS score
        FROM skus s, (SELECT to_tsquery('simple', :tsq) AS query) q
        WHERE :tsq <> '' AND s.search_tsv @@ q.query
        ORDER BY score DESC, s.id LIMIT :k
    ) f
)"""
_TRGM: Final = """
trgm AS (
    SELECT id, 'trgm'::text AS retriever,
           row_number() OVER (ORDER BY score DESC, id) AS rnk, score
    FROM (
        SELECT id, similarity(search_text, :q) AS score
        FROM skus WHERE search_text % :q
        ORDER BY score DESC, id LIMIT :k
    ) t
)"""

_BRANCHES: Final = {"dense": _DENSE, "fts": _FTS, "trgm": _TRGM}


def retrieval_sql(retrievers: tuple[str, ...]) -> TextClause:
    unknown = set(retrievers) - set(_BRANCHES)
    if unknown or not retrievers:
        raise ValueError(f"unknown retrievers: {unknown or retrievers}")
    ctes = ",".join(_BRANCHES[r] for r in retrievers)
    # Identifiers come from the fixed allow-list above; user input is only ever bound.
    union = " UNION ALL ".join(
        f"SELECT id, retriever, rnk, score FROM {r}"  # noqa: S608
        for r in retrievers
    )
    return text(f"WITH {ctes}\n{union}")


def build_tsquery(normalized: str) -> str:
    """OR-query of prefix terms: abbreviations like ``vollm`` match ``vollmilch``.

    Input must already be ``normalize_for_search`` output; the token regex also guarantees no
    tsquery operators reach PostgreSQL.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(normalized):
        tok = raw.strip(".")
        if not tok or tok in seen or (tok.isalpha() and len(tok) < 2):
            continue
        seen.add(tok)
        # Words of >= 3 letters are also matched by prefix; numbers and quantities exactly.
        terms.append(f"'{tok}':*" if tok.isalpha() and len(tok) >= 3 else f"'{tok}'")
        if len(terms) >= _MAX_TERMS:
            break
    return " | ".join(terms)
