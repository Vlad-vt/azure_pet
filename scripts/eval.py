"""Benchmark Dense vs Lexical vs Hybrid RRF on the synthetic invoice benchmark.

Pipeline
1. Retrieve once per golden line (dense + FTS + trigram top-50, unit flags) from PostgreSQL.
2. Fuse offline for every system/config (identical code path to the API: ``engine.fuse``).
3. Tune fusion weights on ``split=dev`` (grid search, MRR@10); report everything on ``split=test``.
4. Paired bootstrap + exact sign test: shipped Hybrid vs Dense and vs Lexical, per slice.
5. Live end-to-end latency (embedding + SQL + fusion) per mode on a sample of test lines.
6. Log to MLflow (``mlruns/``) and write ``docs/eval_report.md`` + README metrics table.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import platform
import re
import time
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from skumatch.config import get_settings
from skumatch.db.session import build_engine, build_sessionmaker
from skumatch.embeddings import OnnxEmbedder
from skumatch.evaluation.metrics import (
    METRICS,
    PairedTest,
    aggregate,
    paired_bootstrap,
    per_query_metrics,
    percentile,
    rank_of,
)
from skumatch.normalize.text import normalize_for_embedding
from skumatch.retrieval import MatchEngine, MatchMode
from skumatch.retrieval.engine import FusionConfig, RetrievalLists, fuse

SLICES = ("abbreviations", "unit_swap", "ocr_typos", "hard_negatives")
TOP_K = 10
README_START = "<!-- EVAL:START -->"
README_END = "<!-- EVAL:END -->"


def load_golden(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def ranks_for(
    lists: list[RetrievalLists], gold: list[dict[str, Any]], mode: MatchMode, cfg: FusionConfig
) -> list[int | None]:
    return [
        rank_of([i for i, _ in fuse(lst, mode, cfg, TOP_K)], g["sku_id"])
        for lst, g in zip(lists, gold, strict=True)
    ]


def tune(
    lists: list[RetrievalLists],
    gold: list[dict[str, Any]],
    base: FusionConfig,
    *,
    require_all: bool,
) -> tuple[FusionConfig, list[dict[str, Any]]]:
    """Grid search on dev. ``require_all`` keeps every retriever's weight > 0 (shipped config)."""
    grid = itertools.product(
        [0.0, 0.25, 0.5, 1.0, 1.5, 2.0],  # w_dense
        [0.0, 0.25, 0.5, 1.0, 1.5],  # w_fts
        [0.5, 1.0, 1.5, 2.0, 3.0],  # w_trgm
        [0.0, 1.0],  # w_unit
    )
    trials: list[dict[str, Any]] = []
    for wd, wf, wt, wu in grid:
        if require_all and (wd == 0 or wf == 0):
            continue
        cfg = replace(base, w_dense=wd, w_fts=wf, w_trgm=wt, w_unit=wu, unit_window=20)
        agg = aggregate(ranks_for(lists, gold, MatchMode.HYBRID, cfg))
        trials.append({"cfg": cfg, **agg})
    # Prefer the simplest config among near-ties (within 0.002 MRR of the best).
    best_mrr = max(t["mrr@10"] for t in trials)
    near = [t for t in trials if t["mrr@10"] >= best_mrr - 0.002]

    def distance(c: FusionConfig) -> float:
        return abs(c.w_dense - 1) + abs(c.w_fts - 1) + abs(c.w_trgm - 1) + c.w_unit

    near.sort(key=lambda t: (-round(t["recall@1"], 4), distance(t["cfg"])))
    return near[0]["cfg"], trials


async def collect(
    engine: MatchEngine, embedder: OnnxEmbedder, gold: list[dict[str, Any]], cfg: FusionConfig
) -> list[RetrievalLists]:
    vecs = embedder.embed([normalize_for_embedding(g["invoice_line"]) for g in gold])
    out: list[RetrievalLists] = []
    for g, v in zip(gold, vecs, strict=True):
        out.append(await engine.retrieve(g["invoice_line"], v, fusion=cfg))
    return out


async def live_latency(
    engine: MatchEngine, lines: list[str], cfg: FusionConfig
) -> dict[str, dict[str, float]]:
    res: dict[str, dict[str, float]] = {}
    for mode in (MatchMode.DENSE, MatchMode.LEXICAL, MatchMode.HYBRID):
        await engine.match(lines[0], mode=mode, fusion=cfg)  # warm-up
        samples = []
        for line in lines:
            t0 = time.perf_counter()
            await engine.match(line, mode=mode, top_k=TOP_K, fusion=cfg)
            samples.append((time.perf_counter() - t0) * 1000)
        res[mode.value] = {"p50_ms": percentile(samples, 50), "p95_ms": percentile(samples, 95)}
    return res


def fmt(x: float) -> str:
    return f"{x:.3f}"


def significance_table(tests: dict[tuple[str, str, str], PairedTest]) -> list[str]:
    lines = [
        "| Slice | Comparison | Metric | Hybrid | Baseline | Δ | 95% CI "
        "| p (bootstrap) | p (sign) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (slc, other, metric), t in tests.items():
        sig = " ✅" if t.significant else ""
        p_sign = f"{t.p_sign:.2g}" if t.p_sign is not None else "—"
        lines.append(
            f"| `{slc}` | Hybrid vs {other} | {metric} | {fmt(t.mean_a)} | {fmt(t.mean_b)} | "
            f"**{t.delta:+.3f}**{sig} | [{t.ci_low:+.3f}, {t.ci_high:+.3f}] | "
            f"{t.p_bootstrap:.2g} | {p_sign} |"
        )
    return lines


def main_table(results: dict[str, dict[str, dict[str, float]]], systems: list[str]) -> list[str]:
    lines = [
        "| System | Slice | R@1 | R@5 | R@10 | MRR@10 | NDCG@10 |",
        "|---|---|---|---|---|---|---|",
    ]
    for slc in (*SLICES, "all"):
        best = {m: max(results[s][slc][m] for s in systems) for m in METRICS}
        for s in systems:
            cells = []
            for m in METRICS:
                v = results[s][slc][m]
                cells.append(f"**{fmt(v)}**" if abs(v - best[m]) < 1e-9 else fmt(v))
            lines.append(f"| {s} | `{slc}` | " + " | ".join(cells) + " |")
    return lines


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = build_engine(settings, url=settings.migration_url)
    embedder = OnnxEmbedder(settings.model_dir, threads=settings.embedding_threads)
    engine = MatchEngine(build_sessionmaker(db), embedder)
    base = FusionConfig.from_settings(settings)
    gold = load_golden(args.golden)
    dev_idx = [i for i, g in enumerate(gold) if g["split"] == "dev"]
    test_idx = [i for i, g in enumerate(gold) if g["split"] == "test"]

    t0 = time.perf_counter()
    lists = await collect(engine, embedder, gold, base)
    collect_s = time.perf_counter() - t0
    print(f"retrieved {len(lists)} lines in {collect_s:.1f}s")

    dev_lists, dev_gold = [lists[i] for i in dev_idx], [gold[i] for i in dev_idx]
    tuned, trials = tune(dev_lists, dev_gold, base, require_all=True)
    unconstrained, _ = tune(dev_lists, dev_gold, base, require_all=False)
    print(f"tuned on dev ({len(dev_idx)} lines): {tuned}")
    print(f"unconstrained dev optimum: {unconstrained}")

    systems: dict[str, tuple[MatchMode, FusionConfig]] = {
        "Dense (HNSW)": (MatchMode.DENSE, base),
        "Lexical (FTS+Trigram RRF)": (MatchMode.LEXICAL, replace(base, w_fts=1.0, w_trgm=1.0)),
        "Hybrid RRF (equal weights)": (
            MatchMode.HYBRID,
            replace(base, w_dense=1.0, w_fts=1.0, w_trgm=1.0, w_unit=0.0),
        ),
        "Hybrid RRF (dev-tuned, shipped)": (MatchMode.HYBRID, tuned),
    }
    ablations: dict[str, tuple[MatchMode, FusionConfig]] = {
        "FTS only": (MatchMode.LEXICAL, replace(base, w_fts=1.0, w_trgm=0.0)),
        "Trigram only": (MatchMode.LEXICAL, replace(base, w_fts=0.0, w_trgm=1.0)),
        "Hybrid, no dense": (MatchMode.HYBRID, replace(tuned, w_dense=0.0)),
        "Hybrid, no FTS": (MatchMode.HYBRID, replace(tuned, w_fts=0.0)),
        "Hybrid, no trigram": (MatchMode.HYBRID, replace(tuned, w_trgm=0.0)),
        "Dev optimum, unconstrained": (MatchMode.HYBRID, unconstrained),
        "Hybrid + unit-agreement list": (
            MatchMode.HYBRID,
            replace(tuned, w_unit=1.0, unit_window=20),
        ),
    }
    shipped = "Hybrid RRF (dev-tuned, shipped)"

    test_gold = [gold[i] for i in test_idx]
    test_lists = [lists[i] for i in test_idx]
    all_ranks: dict[str, list[int | None]] = {}
    results: dict[str, dict[str, dict[str, float]]] = {}
    for name, (mode, cfg) in {**systems, **ablations}.items():
        ranks = ranks_for(test_lists, test_gold, mode, cfg)
        all_ranks[name] = ranks
        by_slice: dict[str, list[int | None]] = defaultdict(list)
        for g, r in zip(test_gold, ranks, strict=True):
            by_slice[g["slice"]].append(r)
        results[name] = {s: aggregate(by_slice[s]) for s in SLICES}
        results[name]["all"] = aggregate(ranks)

    tests: dict[tuple[str, str, str], PairedTest] = {}
    for slc in (*SLICES, "all"):
        idx = [i for i, g in enumerate(test_gold) if slc == "all" or g["slice"] == slc]
        for other in ("Dense (HNSW)", "Lexical (FTS+Trigram RRF)", "Trigram only"):
            for metric in ("recall@1", "mrr@10"):
                a = [per_query_metrics(all_ranks[shipped][i])[metric] for i in idx]
                b = [per_query_metrics(all_ranks[other][i])[metric] for i in idx]
                label = other if other == "Trigram only" else other.split(" ")[0]
                tests[(slc, label, metric)] = paired_bootstrap(a, b, metric)

    rng = np.random.default_rng(42)
    sample = [
        test_gold[i]["invoice_line"] for i in rng.permutation(len(test_gold))[: args.latency_n]
    ]
    latency = await live_latency(engine, sample, tuned)
    await db.dispose()

    # ---------------------------------------------------------------- error analysis
    misses = []
    for g, lst, r in zip(test_gold, test_lists, all_ranks[shipped], strict=True):
        if r != 1:
            top = fuse(lst, MatchMode.HYBRID, tuned, 1)
            pred = lst.skus.get(top[0][0]) if top else None
            truth = lst.skus.get(g["sku_id"])
            misses.append(
                {
                    "line": g["invoice_line"],
                    "slice": g["slice"],
                    "rank": r,
                    "pred": pred,
                    "truth": truth,
                    "truth_id": g["sku_id"],
                }
            )

    judge_summary = None
    if args.llm_judge:
        from skumatch.evaluation.llm_judge import LLMJudge

        judge = LLMJudge.from_env()
        if judge is None:
            print("--llm-judge requested but no OPENAI_API_KEY/GEMINI_API_KEY set: skipping")
        else:
            verdicts = []
            for m in misses[: args.llm_judge_max]:
                if m["pred"] is None or m["truth"] is None:
                    continue
                desc = lambda s: f"{s['brand']} {s['name']} {s['quantity_raw']}"  # noqa: E731
                verdicts.append(
                    judge.judge(m["line"], desc(m["truth"]), desc(m["pred"])).equivalent
                )
            judge_summary = {
                "provider": judge.provider,
                "model": judge.model,
                "judged": len(verdicts),
                "equivalent_rate": float(np.mean(verdicts)) if verdicts else 0.0,
            }

    # ---------------------------------------------------------------- MLflow
    run_id = None
    if not args.no_mlflow:
        import mlflow

        # Local, server-less tracking: SQLite metadata + artifacts under mlruns/ (git-ignored).
        # (MLflow 3 put the plain file store in maintenance mode.)
        mlruns = Path("mlruns").resolve()
        mlruns.mkdir(exist_ok=True)
        mlflow.set_tracking_uri(f"sqlite:///{mlruns / 'mlflow.db'}")
        if mlflow.get_experiment_by_name("skumatch-eval") is None:
            mlflow.create_experiment(
                "skumatch-eval", artifact_location=(mlruns / "artifacts").as_uri()
            )
        mlflow.set_experiment("skumatch-eval")
        with mlflow.start_run(run_name=time.strftime("eval-%Y%m%d-%H%M%S")) as parent:
            run_id = parent.info.run_id
            mlflow.log_params({f"tuned_{k}": v for k, v in asdict(tuned).items()})
            mlflow.log_params({"n_test": len(test_idx), "n_dev": len(dev_idx), "top_k": TOP_K})
            for mode, lat in latency.items():
                mlflow.log_metrics({f"latency_{mode}_{k}": v for k, v in lat.items()})
            for name in results:
                slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
                with mlflow.start_run(run_name=slug, nested=True):
                    mode, cfg = {**systems, **ablations}[name]
                    mlflow.log_params({"mode": mode.value, **asdict(cfg)})
                    for slc, agg in results[name].items():
                        mlflow.log_metrics(
                            {f"{slc}.{m.replace('@', '_at_')}": v for m, v in agg.items()}
                        )
            report_tmp = Path("mlruns") / "last_misses.jsonl"
            report_tmp.write_text(
                "\n".join(json.dumps(m, ensure_ascii=False, default=str) for m in misses)
            )
            mlflow.log_artifact(str(report_tmp))

    # ---------------------------------------------------------------- report
    headline = list(systems)
    md = [
        "# Evaluation Report",
        "",
        "Generated by `make eval` (`scripts/eval.py`). Benchmark: `data/golden_eval.jsonl` "
        f"(seed=42) — **{len(test_idx)} test lines** reported, {len(dev_idx)} dev lines used only "
        "for fusion-weight tuning. Catalog: 8,000 Open Food Facts DE SKUs in PostgreSQL 16 + "
        "pgvector (HNSW). Candidates per retriever: "
        f"{base.candidates}; RRF k = {tuned.k}.",
        "",
        f"Environment: {platform.processor() or platform.machine()}, {platform.python_version()}, "
        f"ONNX Runtime CPU, INT8 `multilingual-e5-small`. MLflow run: `{run_id}`.",
        "",
        "## Headline (test split, all slices)",
        "",
        "| System | R@1 | R@5 | R@10 | MRR@10 | NDCG@10 |",
        "|---|---|---|---|---|---|",
    ]
    for s in headline:
        agg = results[s]["all"]
        md.append(f"| {s} | " + " | ".join(fmt(agg[m]) for m in METRICS) + " |")
    md += [
        "",
        "## Per slice",
        "",
        *main_table(results, headline),
        "",
        "## Statistical significance (shipped Hybrid vs single methods)",
        "",
        "Paired bootstrap (10,000 resamples, one-sided H1: Hybrid > baseline) on per-query "
        "metrics, plus an exact one-sided sign test (McNemar) on discordant pairs for R@1. ✅ = "
        "both p < 0.05.",
        "",
        *significance_table(tests),
        "",
        "## Ablations (test split, all slices)",
        "",
        "| Variant | R@1 | R@5 | R@10 | MRR@10 | NDCG@10 |",
        "|---|---|---|---|---|---|",
    ]
    for s in (*ablations, shipped):
        agg = results[s]["all"]
        md.append(f"| {s} | " + " | ".join(fmt(agg[m]) for m in METRICS) + " |")
    md += [
        "",
        "## Fusion weights tuned on dev",
        "",
        f"Grid of {len(trials)} configs (w_dense, w_fts, w_trgm, w_unit) with every retriever "
        "weight > 0 (the shipped system must stay hybrid, see notes), selected by dev MRR@10; "
        "near-ties (±0.002) → higher R@1 → closest to equal weights. Unconstrained dev optimum "
        f"(zero weights allowed): `w_dense={unconstrained.w_dense} w_fts={unconstrained.w_fts} "
        f"w_trgm={unconstrained.w_trgm} w_unit={unconstrained.w_unit}`.",
        "",
        "```text",
        f"w_dense={tuned.w_dense} w_fts={tuned.w_fts} w_trgm={tuned.w_trgm} "
        f"w_unit={tuned.w_unit} unit_window={tuned.unit_window} k={tuned.k}",
        "```",
        "",
        "## Latency (live, end-to-end: embedding + SQL + fusion, sequential)",
        "",
        f"{len(sample)} random test lines, local PostgreSQL, ORT threads = "
        f"{settings.embedding_threads or 'default'}.",
        "",
        "| Mode | p50 (ms) | p95 (ms) |",
        "|---|---|---|",
    ]
    for mode, lat in latency.items():
        md.append(f"| {mode} | {lat['p50_ms']:.1f} | {lat['p95_ms']:.1f} |")
    md += ["", "## Error analysis (shipped Hybrid, test misses at R@1)", ""]
    by_slice_miss: dict[str, int] = defaultdict(int)
    for m in misses:
        by_slice_miss[m["slice"]] += 1
    md.append(
        f"{len(misses)} misses: "
        + ", ".join(f"`{s}` {by_slice_miss.get(s, 0)}" for s in SLICES)
        + ". Sample:"
    )
    md += [
        "",
        "| Slice | Invoice line | Predicted #1 | Ground truth | GT rank |",
        "|---|---|---|---|---|",
    ]
    shown: dict[str, int] = defaultdict(int)
    for m in misses:
        if shown[m["slice"]] >= 3 or not m["pred"] or not m["truth"]:
            continue
        shown[m["slice"]] += 1
        p, t = m["pred"], m["truth"]
        md.append(
            f"| `{m['slice']}` | `{m['line']}` | {p['brand']} — {p['name']} {p['quantity_raw']} | "
            f"{t['brand']} — {t['name']} {t['quantity_raw']} | {m['rank'] or '>10'} |"
        )
    notes = Path("docs/eval_notes.md")
    if notes.exists():
        md += ["", notes.read_text(encoding="utf-8").strip()]
    if judge_summary:
        md += [
            "",
            "## LLM-as-a-judge (optional)",
            "",
            f"{judge_summary['judged']} misses judged by {judge_summary['provider']} "
            f"`{judge_summary['model']}`: {judge_summary['equivalent_rate']:.0%} were judged "
            "equivalent products (label noise / duplicate SKUs).",
        ]
    md.append("")
    args.out.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {args.out}")

    # README table
    readme = Path("README.md")
    table = [
        README_START,
        "",
        "| System | R@1 | R@5 | R@10 | MRR@10 | NDCG@10 |",
        "|---|---|---|---|---|---|",
    ]
    for s in headline:
        agg = results[s]["all"]
        table.append(f"| {s} | " + " | ".join(fmt(agg[m]) for m in METRICS) + " |")
    table += ["", "Per-slice: [`docs/eval_report.md`](docs/eval_report.md).", "", README_END]
    text = readme.read_text(encoding="utf-8")
    if README_START in text and README_END in text:
        pre, rest = text.split(README_START, 1)
        _, post = rest.split(README_END, 1)
        readme.write_text(pre + "\n".join(table) + post, encoding="utf-8")
    summary = {
        "tuned": asdict(tuned),
        "all": {s: results[s]["all"] for s in headline},
        "latency": latency,
        "significant": {f"{k[0]}|{k[1]}|{k[2]}": v.significant for k, v in tests.items()},
    }
    Path("docs/eval_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--golden", type=Path, default=Path("data/golden_eval.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("docs/eval_report.md"))
    parser.add_argument("--latency-n", type=int, default=200)
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument(
        "--llm-judge", action="store_true", help="needs OPENAI_API_KEY or GEMINI_API_KEY"
    )
    parser.add_argument("--llm-judge-max", type=int, default=50)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
