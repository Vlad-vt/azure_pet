"""Build the DE/EU product catalog from the Open Food Facts Hugging Face Parquet dump.

Downloads ``openfoodfacts/product-database/food.parquet`` (~7.7 GB, cached in ``data/raw``),
streams it column-projected, keeps products sold in Germany with a German name, brand,
parseable quantity and category, de-duplicates near-identical SKUs and writes the
``--limit`` most-scanned products to ``data/catalog.parquet`` (committed, ~1 MB).

Data © Open Food Facts contributors, ODbL 1.0 (https://world.openfoodfacts.org/data).
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from skumatch.normalize import normalize_for_search, parse_quantity

REPO = "openfoodfacts/product-database"
COLUMNS = [
    "code",
    "product_name",
    "brands",
    "quantity",
    "categories_tags",
    "countries_tags",
    "lang",
    "unique_scans_n",
    "completeness",
]
_NAME_OK = re.compile(r"^[\w\s.,%&'+\-/()äöüÄÖÜßéèàçñ!]+$", re.UNICODE)
_EAN_OK = re.compile(r"^\d{8,14}$")
_ESTIMATED_SIGN = re.compile(r"\s*(?:℮|\be\b)\s*$")


def _pick_name(names: list[dict[str, str]] | None, product_lang: str | None) -> str | None:
    if not names:
        return None
    by_lang = {n.get("lang"): (n.get("text") or "").strip() for n in names}
    name = by_lang.get("de") or (by_lang.get("main") if product_lang == "de" else None)
    if not name or not (3 <= len(name) <= 80) or not _NAME_OK.match(name):
        return None
    return " ".join(name.split())


def _category(tags: list[str] | None) -> tuple[str, str] | None:
    if not tags:
        return None
    en = [t[3:].replace("-", " ") for t in tags if t.startswith("en:")]
    if not en:
        return None
    return en[-1], " > ".join(en[:4])


def _first_brand(brands: str | None) -> str | None:
    if not brands:
        return None
    brand = brands.split(",")[0].strip()
    return brand if 2 <= len(brand) <= 40 else None


def build(parquet_path: Path, limit: int) -> pa.Table:
    pf = pq.ParquetFile(parquet_path)
    rows: list[dict[str, Any]] = []
    for batch in pf.iter_batches(columns=COLUMNS, batch_size=50_000):
        for r in batch.to_pylist():
            countries = r["countries_tags"] or []
            if "en:germany" not in countries:
                continue
            code = (r["code"] or "").strip()
            if not _EAN_OK.match(code):
                continue
            name = _pick_name(r["product_name"], r["lang"])
            brand = _first_brand(r["brands"])
            cat = _category(r["categories_tags"])
            qty_raw = _ESTIMATED_SIGN.sub("", " ".join((r["quantity"] or "").split()))
            qty = parse_quantity(qty_raw)
            if not (name and brand and cat and qty) or qty.unit == "pc":
                continue
            rows.append(
                {
                    "ean": code,
                    "name": name,
                    "brand": brand,
                    "quantity_raw": qty_raw[:40],
                    "qty_count": qty.count,
                    "qty_amount": qty.amount,
                    "qty_unit": qty.unit,
                    "quantity": qty.token(),
                    "category": cat[0],
                    "category_path": cat[1],
                    "countries": ",".join(c[3:] for c in countries if c.startswith("en:"))[:200],
                    "scans": int(r["unique_scans_n"] or 0),
                    "completeness": float(r["completeness"] or 0.0),
                }
            )
    print(f"candidates after filters: {len(rows)}")
    rows.sort(key=lambda x: (-x["scans"], -x["completeness"], x["ean"]))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        brand_norm = normalize_for_search(row["brand"])
        name_norm = normalize_for_search(row["name"])
        if brand_norm not in name_norm:
            name_norm = f"{brand_norm} {name_norm}"
        key = f"{name_norm}|{row['quantity']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    for i, row in enumerate(out, start=1):
        row["sku_id"] = i
    table = pa.Table.from_pylist(out)
    cols = ["sku_id"] + [c for c in table.column_names if c != "sku_id"]
    return table.select(cols)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=8000)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/catalog.parquet"))
    parser.add_argument("--parquet", type=Path, default=None, help="use an existing local dump")
    args = parser.parse_args()

    if args.out.exists() and args.parquet is None and not os.environ.get("SKUMATCH_REFETCH"):
        print(f"{args.out} exists (committed); set SKUMATCH_REFETCH=1 to rebuild from OFF")
        return
    path = args.parquet or Path(
        hf_hub_download(REPO, "food.parquet", repo_type="dataset", local_dir=args.raw_dir)
    )
    table = build(path, args.limit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, args.out, compression="zstd")
    print(f"wrote {table.num_rows} SKUs -> {args.out}")


if __name__ == "__main__":
    main()
