"""Generate the labelled invoice-line benchmark (``data/golden_eval.jsonl``) with seed=42."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq

from skumatch.data.synth import CatalogItem, InvoiceLineGenerator


def load_catalog(path: Path) -> list[CatalogItem]:
    rows = pq.read_table(path).to_pylist()
    return [
        CatalogItem(
            sku_id=int(r["sku_id"]),
            name=r["name"],
            brand=r["brand"],
            quantity_raw=r["quantity_raw"],
            qty_count=int(r["qty_count"]),
            qty_amount=float(r["qty_amount"]),
            qty_unit=r["qty_unit"],
            category=r["category"],
        )
        for r in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.parquet"))
    parser.add_argument("--out", type=Path, default=Path("data/golden_eval.jsonl"))
    parser.add_argument("--per-slice", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    lines = InvoiceLineGenerator(catalog, seed=args.seed).generate(n_per_slice=args.per_slice)
    with args.out.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line.to_dict(), ensure_ascii=False) + "\n")
    print(f"wrote {len(lines)} labelled lines -> {args.out}")


if __name__ == "__main__":
    main()
