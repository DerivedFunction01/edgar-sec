# `defs/sec_forms/page_markers/` — Coordinate-Safe Page-Marker Analysis and Cleanup

Owns ASCII/SGML and HTML page-marker discovery, classification, and safe
coordinate-aware removal. No phase-local serializers or regexes; all
heuristics are structural, statistical, or prose-guarded.

---

## Layout

```text
defs/sec_forms/page_markers/
  __init__.py          # Stable public API re-exports
  models.py            # Marker, candidate, run, evidence, terminal-state, region, and boundary models
  constants.py         # Empirical prose stop-word set (42 words) and tuning constants
  prose.py             # Shared prose classifier (ASCII/HTML stop-word guard, template detector)
  ascii.py             # ASCII/SGML orchestration and validated cleanup
  html.py              # HTML discovery: DOM pruning, table-footers, strong-label gate, regions, recovery
  candidates.py        # Firm patterns, contextual candidates, and promotion (ASCII slot logic)
  headers.py           # Repeated header/footer evidence and ASCII slot-invariant policy
  sequence.py          # Namespace-aware validation, healing, inference, and monotone-fraction checks
  layout.py            # Alignment, spacing, and table-shape guards
  pre.py               # SGML PRE-block discrimination and marker sanitation
```

---

## Key Modules

- **`models.py`** — `PageMarkerAnalysis`, `CandidateSource`, `TerminalState`,
  `PageRegionReport`, `InferredBoundary`. Regions carry `referential_labels`,
  `weak_numeric`, and `likely_pageless` flags; inferred boundaries are
  metadata-only and never authorize removal on their own.

- **`constants.py`** — `PROSE_GUARD_STOP_WORDS` (42 words), empirically
  derived from the full 2,202-fixture corpus (footer_df==0, body_df>=25%).
  Tuning constants for gap caps, family-extent lookback, and cell-count limits.

- **`prose.py`** — Shared prose classifier (`looks_like_prose`, `prose_stop_words`).
  Used by both HTML and ASCII paths to distinguish unique prose from repeated
  footer/header templates. Unique prose is always preserved; repeated prose
  templates may be removable.

- **`ascii.py`** — ASCII/SGML orchestration. Delegates slot analysis to
  `candidates.py` and `headers.py`, then runs `sequence.py` healing and
  inference. Validates final strips before applying.

- **`html.py`** — HTML discovery pipeline:
  - `_NodeFacts` per-enrichment memo (hidden/toc/break ancestor walks,
    attr_text, node_text, semantic) shared across HR/table/generic strategies.
  - Occupied-container pruning via `_CONTAINER_SKIP_TAGS` (div/span/section/
    table/tbody/tr/center); element-children containers skip deep text, so the
    innermost node is the marker.
  - Table-footer candidates (`_table_footer_candidates`): repeated one-row
    footer-table families, financial guards (currency/percent/decimal/paren/
    date/multiyear family-wide), prose stop-word guard via `LexicalMatcher`
    (≥2 distinct hits), cell-count cap ≤8, cell text ≤200 chars; section-split
    at value restarts.
  - Strong-label raw gate (`_raw_label_tags` + `html_has_page_label_evidence`):
    `F-N`/`page N` tokens, page-semantic attrs, page-break styles.
  - Complement interval search: `_family_extents()` (2 literal anchors/family),
    `_region_reports()` → `PageRegionReport` attached to `PageMarkerAnalysis.regions`.
  - `_recover_run_gaps()` → `InferredBoundary(reason="bounded_literal_recovery")`
    metadata-only; zero-cost when no gaps exist.

- **`candidates.py`** — ASCII `all_candidates` first/last-quarter selection,
  slot promotion rules, and template detection.

- **`headers.py`** — Repeated header/footer evidence. ASCII slot-invariant
  policy: prose-looking lines need a repeated template (≥2) within the slot;
  unique prose is preserved. Uses `prose.py` for shared classification.

- **`sequence.py`** — Namespace-aware validation, `heal_run` monotone
  interpolation, `monotone_fraction` reporting, and inferred-boundary
  generation. ASCII `heal_run` gap interpolation is capped (mirrors the HTML
  `_RECOVERY_MAX_GAP` boundary) to prevent runaway inferred boundaries on
  long documents.

- **`layout.py`** — Alignment, spacing, and table-shape guards used by
  candidates and headers.

- **`pre.py`** — SGML PRE-block discrimination: distinguishes real page-marker
  PRE content from boilerplate, then sanitizes markers inside validated blocks.

---

## Safety Invariants

1. **Page-number removal is independent of header removal.** The two signals
   are evaluated separately; removal of one does not imply removal of the other.
2. **Unique prose is preserved.** Repeated prose templates may be removable,
   but any line with unique prose content is never stripped.
3. **Promotion requires ≥2 independent signals.** A candidate must clear
   namespace sequence, layout/TOC, prose, and financial/table exclusion gates
   before it is promoted.
4. **Metadata-only inferred boundaries never authorize removal.**
   `InferredBoundary` records gaps and bounded recoveries for reporting and
   debugging, but removal is permitted only from accepted literal runs.
5. **Bare digits are never strong raw evidence.** Page numbers must carry
   semantic context (labels, attrs, styles) or structural repetition to be
   considered.
6. **ASCII `heal_run` gaps are capped.** Interpolation beyond the cap is
   recorded but does not produce removal-authorizing inferred boundaries.

---

## Performance

Iterative optimization of the HTML/ASCII pipeline achieved an **81× speedup**
on the 16-doc benchmark (524.5s → 6.47s). Form-level improvements include
form10-k (142s → 2.85s) and v217619 (322s → 0.66s).

Key optimizations:
- Occupied-container pruning eliminates deep text walks inside non-marker
  containers.
- `_NodeFacts` memoization shares expensive ancestor/attr walks across HR,
  table, and generic strategies.
- Table-footer promotion is family-aware (one-row repeated tables) with
  early financial guards.
- Section-split group validation and `_group_is_toc_like()` sibling-signature
  rejection reduce false positives from TOC rows.
- Complement interval search bounds recovery to literal anchor families
  instead of scanning the full document.

---

## Benchmark Harnesses

- `/tmp/kilo/bench_table_footer.py` — 16-doc set (10 misses + 6 controls).
- `/tmp/kilo/scale_test_50.py` — 50 stratified docs, 8 workers.
- `/tmp/kilo/probe_complement.py` — Region/recovery probe.

Current 50-doc scale results: 50/50 ok, 0 errors, 1.8 docs/s, 3.2 MB/s,
p50=2081ms, 180 runs, 5628 markers.

---

## Known Caveats

- ASCII `heal_run` gap interpolation on very long documents (e.g. `d50363_10k.txt`,
  255 KB) can produce a high count of `interpolated_gap` inferred boundaries
  before the cap is enforced. The cap mirrors the HTML `_RECOVERY_MAX_GAP`
  boundary; verify the cap constant in `sequence.py` before assuming the
  inferred-boundary volume is sane.
- Recovery tag-context can anchor to TOC rows when bracketing anchors are
  ambiguous. A corpus-prior recipe cache is flagged as a future guard but is
  not yet implemented.
- Selectolax drops boolean `hidden` attrs; hidden-ancestor detection is
  selectolax-aware but may miss some edge cases present in bs4.
- `FastHtmlNode` lacks `find_previous_sibling`; the HR short-circuit is
  currently bs4-harness-only.

---

## Tests

- 52 page-marker contract tests in `defs/tests/test_page_markers.py`.
- Run: `.venv/bin/pytest defs/tests`
