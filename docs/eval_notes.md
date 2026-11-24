## Benchmark history & honest reading of the results

**v1 → v2.** The first benchmark run (generator v1, looser catalog de-duplication) saturated:
all systems scored R@1 0.94–0.96 on test (Dense 0.962, Lexical 0.940, Hybrid 0.963) and Dense hit
1.000 on `hard_negatives`, so differences sat on the ceiling. Error analysis showed two causes,
both fixed *before* re-running and independent of which method benefits:

1. **Label noise** — Open Food Facts near-duplicates (`REWE Bio | Bio Gemüsebrühe` vs
   `REWE Bio | Gemüsebrühe`, `i.Tr.` vs `i. Tr.`, re-ordered names). Catalog de-duplication now
   uses order/punctuation-insensitive token-set keys (`scripts/fetch_off.py::dedup_keys`).
2. **Too-mild noise** — v2 omits the brand on 20% of abbreviated lines, rotates word order,
   raises the OCR confusion rate to 10–20% and abbreviates the shared tokens of hard-negative
   lines like a real supplier would.

**What the numbers say (v2, shipped dev-tuned weights).**
- **Overall**, Hybrid RRF is significantly better than Dense (R@1 +0.027) and than Lexical
  FTS+Trigram RRF (R@1 +0.033); both p < 0.001 (paired bootstrap and exact sign test).
- **`ocr_typos`**: Hybrid significantly beats *both* Dense (+0.035 R@1) and Lexical (+0.131) ✅.
- **`hard_negatives`**: Hybrid significantly beats Lexical (+0.021 R@1) but is **statistically
  tied with Dense** (+0.008, p = 0.23); Dense already resolves 97.9% of these lines. The
  stage-4 hypothesis is therefore confirmed for `ocr_typos` and only partially for
  `hard_negatives`.
- The gains are complementary: lexical signals rescue abbreviations (Dense 0.83 → Hybrid 0.90),
  dense signals rescue OCR damage that defeats FTS (Lexical 0.86 → Hybrid 0.99).
- **Trigram-only is a strong baseline here** (R@1 0.971, tied with Hybrid, p ≈ 0.85). The
  synthetic noise is mostly character-level (truncation, OCR swaps), exactly what trigrams model,
  and dev tuning accordingly up-weights trigram (`w_trgm=1.5`, `w_dense=0.5`, `w_fts=0.25`). The
  unconstrained dev optimum (zero weights allowed) still keeps all three retrievers, and Hybrid is
  never significantly worse than the best single retriever on any slice. We ship Hybrid for
  robustness to variation the generator does not model (paraphrases, EN/DE mixing, supplier
  naming conventions); a cross-lingual/paraphrase slice is the next benchmark addition.
- Dev tuning also re-enabled the unit-agreement list (`w_unit=1.0`, window 20); its effect on
  test is neutral (ablation table), so it is a tie-breaker rather than a driver.

**Caveats.** Synthetic labels are generated from the same catalog text the retrievers index;
real invoices will be harder. 911 test lines give ±1–2 pp confidence intervals, so differences
below ~1.5 pp R@1 should be read as ties.
