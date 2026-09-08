# `defs/sec_forms/page_markers/` — Coordinate-Safe Page-Marker Analysis and Cleanup

Owns ASCII/SGML page-marker discovery, classification, and safe
coordinate-aware removal. HTML callers use the string-first
`fast_html/` adapter which renders HTML to break-text before
delegating to the ASCII orchestrator. No phase-local serializers or
regexes; all heuristics are structural, statistical, or prose-guarded.

---

## Layout

```text
defs/sec_forms/page_markers/
  __init__.py          # Stable public API re-exports
  models.py            # Marker, candidate, run, evidence, terminal-state, region, and boundary models
  constants.py         # Empirical prose stop-word set (42 words) and tuning constants
  prose.py             # Shared prose classifier (ASCII/HTML stop-word guard, template detector)
  artifacts.py         # Canonical page-artifact tokens, template normalization, and metadata
  sequence.py          # Namespace-aware validation, healing, inference, and monotone-fraction checks
  fast_html/           # String-first HTML break-to-text converter and page policy adapter
    __init__.py        # Public API re-exports
    converter.py       # HTML-to-break-text conversion and ASCII delegation
  ascii/               # ASCII/SGML-specific subpackage
    __init__.py        # Re-exports all public ASCII functions
    orchestrator.py    # ASCII/SGML analysis orchestration (markers, runs, inference)
    policy.py          # Coordinate-safe application of validated decisions (strip/annotate/preserve)
    candidates.py      # Firm patterns, contextual candidates, and promotion (ASCII slot logic)
    headers.py         # Repeated header/footer evidence and local-cohort furniture policy
    layout.py          # Alignment, spacing, and table-shape guards
    pre.py             # SGML PRE-block discrimination and marker sanitation
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

- **`ascii/orchestrator.py`** — ASCII/SGML analysis orchestration. Delegates slot
  analysis to `ascii/candidates.py` and `ascii/headers.py`, then runs
  `sequence.py` healing and inference.

- **`ascii/policy.py`** — Coordinate-safe application of validated decisions.
  `strip_page_markers()` applies only REMOVE/NORMALIZE decisions in the same
  source frame; `apply_page_markers()` implements the `strip`/`annotate`/
  `preserve` artifact policy with merged ranges, reverse-order rewriting, and
  template-id provenance.

- **`ascii/headers.py`** — Repeated header/footer evidence. Bounded block
  windows: for each accepted page anchor the analyzer walks forward (headers)
  and backward (footers), skipping blanks, and collects up to 8 non-empty
  lines / 1200 characters, stopping at other anchors, structural tags, and
  `<TABLE>` boundaries. Normalized line templates are grouped by
  `(side, slot, template)` and evaluated in **local anchor clusters** (gap
  ≤ 2, local density ≥ 0.65, ≥ 3 anchors), never against a document-wide
  denominator, so a 5-page appendix run inside a 300-page filing survives.
  Roles drive retention: `boilerplate`/`footer` remove all occurrences,
  `section_header` (variable content in a stable slot) keeps the first
  occurrence per cohort, `unknown` preserves. Fully validated adjacent lines
  merge into one block span before removal; ASCII `<TABLE>` units are
  excluded unless `allow_table_furniture` is set (HTML path only, where
  rendered table furniture is removed atomically including wrappers).
  Structural `<PAGE>` anchors alone (no numeric labels) authorize furniture
  detection. Uses `prose.py` for shared classification.

- **`sequence.py`** — Namespace-aware validation, `heal_run` monotone
  interpolation, `monotone_fraction` reporting, and inferred-boundary
  generation. ASCII `heal_run` gap interpolation is capped (mirrors the HTML
  `_RECOVERY_MAX_GAP` boundary) to prevent runaway inferred boundaries on
  long documents.

- **`ascii/layout.py`** — Alignment, spacing, and table-shape guards used by
  `ascii/candidates.py` and `ascii/headers.py`.

- **`ascii/pre.py`** — SGML PRE-block discrimination: distinguishes real page-marker
  PRE content from boilerplate, then sanitizes markers inside validated blocks.

Shared cover healing is provided by `defs.sec_forms.cover.healing.heal_cover_text()`,
which applies representation-neutral healing to bounded cover slices. The retained
`defs.text.html.tree.py` module provides parser/table-node infrastructure
(selectolax wrapper, CSS traversal, raw-node access, cell text extraction) for
table rendering and independent research consumers; it is not a document
normalization API.

---

## Safety Invariants

1. **Page-number removal is independent of header removal.** The two signals
   are evaluated separately; removal of one does not imply removal of the other.
2. **Unique prose is preserved.** Repeated prose templates may be removable,
   but any line with unique prose content is never stripped. Removal now
   requires a repeated normalized template inside a local anchor cluster, so
   unique prose cannot clear the evidence bar.
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

The string-first HTML/ASCII pipeline achieves high throughput by
rendering HTML to break-text via `defs.text.html.normalize_html_document`
before delegating to the ASCII orchestrator. Key optimizations:
- Occupied-container pruning eliminates deep text walks inside non-marker
  containers.
- Table-footer promotion is family-aware (one-row repeated tables) with
  early financial guards.
- Section-split group validation and `_group_is_toc_like()` sibling-signature
  rejection reduce false positives from TOC rows.
- Complement interval search bounds recovery to literal anchor families
  instead of scanning the full document.
- Tagged-table protection via `mask_tagged_tables`/`restore_tagged_tables`
  prevents whitespace-oriented passes from seeing table layout.

---

## Page Artifacts (Rendered Provenance)

Validated page-marker decisions survive rendering as page artifacts.
`PageArtifactPolicy` (`strip` / `annotate` / `preserve`) is declared at the
normalizer boundary:

- `strip` removes validated furniture and records provenance in the
  `page_artifacts` metadata; no visible token is emitted (legacy behavior).
- `annotate` replaces each validated span with a compact,
  ASCII-safe token line — `[[SEC:PAGE_BREAK id=N]]`,
  `[[SEC:REPEATING_HEADER id=N]]`, `[[SEC:REPEATING_FOOTER id=N]]` — where `N`
  is assigned in document order. All payload attributes (page number,
  namespace, source kind, line span, removability,
  `template_id`) live in the artifact metadata, never in the token.
- `preserve` leaves the source representation unchanged.

Key contracts (`artifacts.py`, `ascii/orchestrator.py`, `fast_html/converter.py`):

- Generated tokens are never classified as source page markers; re-running
  analysis over annotated text is idempotent.
- Metadata-only inference emits no visible HTML artifact; ASCII inferred-line
  boundaries may emit one at their line coordinate and are never removable.
- Repeating header/footer furniture deduplicates into templates keyed by the
  SHA-1 of normalized rendered text (digit runs collapse to `#`), so repeating
  an Apple-style footer 120 times costs one template entry plus per-page
  coordinates.
- `build_page_artifact_metadata()` returns the deterministic sidecar persisted
  under `processor_metadata.page_artifacts` in phase 025 storage; a missing
  key means legacy `strip` behavior.

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
- The string-first HTML path renders via `defs.text.html.normalize_html_document`
  before ASCII analysis; complex nested HTML shapes may produce different
  break-text than a DOM-based approach would.
- Selectolax drops boolean `hidden` attrs; hidden-ancestor detection is
  selectolax-aware but may miss some edge cases present in bs4.

---

## Tests

- Page-marker contract tests in `defs/tests/test_page_markers.py` (furniture
  engine, cohorts, retention roles, unnumbered `<PAGE>` anchors) and HTML
  adapter tests in `defs/tests/test_fast_html_page_markers.py` (rendered
  table furniture, break-text conversion, policy application).
- Run: `.venv/bin/pytest defs/tests`
