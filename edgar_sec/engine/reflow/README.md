# `edgar_sec/engine/reflow` — conservative ASCII prose reflow driven by a calibrated rule engine

Un-wraps hard-wrapped 72-to-80-column ASCII prose into flowing paragraphs without scrambling
the tables, signature blocks, and financial grids sharing the same page. It also tags the
untagged tables it finds along the way, and publishes the line mapper that lets every other
stage's line anchors survive the renumbering reflow causes.

## Purpose

Between roughly 1990 and 2005 EDGAR filings were plain text, hard-wrapped at the column. A
paragraph arrives as eight lines. Naive joining breaks everything else on the page: a financial
matrix stops being a matrix, a signature block stops being a signature block.

This package answers "is this run of lines prose or layout?" with a declarative rule cascade
over a registry of scalar features, and it answers "preserve" by default. The final rule in
the cascade is `default_preserve_ambiguous`, and its stated rationale is the whole design:
"Ambiguous or unverified block preserved to guarantee zero table corruption"
(`rules.py:518-523`).

The composition seam is `edgar_sec/engine/forms/normalize.py`; this package exposes
`reflow_ascii` and a `ReflowPolicy`, and knows nothing about forms.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `types.py` | The vocabulary: the three action constants `ACTION_UNWRAP`, `ACTION_PRESERVE`, `ACTION_TAG_AND_PRESERVE`; the frozen `ReflowPolicy` dataclass of six boolean toggles and six callables; the `SpanDecision` and `ReflowResult` records; `_MIN_PROSE_ALPHA_DENSITY = 0.55`; and `build_line_mapper`. |
| `context.py` | `BlockContext` — the feature surface. Roughly 60 `cached_property` accessors over a block's lines: intrinsic booleans, geometry (gutter count, shared numeric columns, bilateral insets), windowed alpha/numeric densities in four 20-column windows, linguistic counts, and interline-wrap statistics. Also `FINANCIAL_TABLE_BRIDGE_RE`, `_EXHIBIT_PHRASES`, `to_feature_dict`, `to_feature_vector` (NumPy). |
| `registry.py` | `FEATURE_REGISTRY` — 44 `FeatureSpec` entries grouped as intrinsic booleans, continuous floats, and discrete counts, each with a `default_predicate` and a calibrated `optimal_threshold`; seven carry a `hypothesis_ref` (`H-GEO-11` through `H-GEO-18`). |
| `features.py` | The eager feature extractor. `_compute_features` walks a tuple of lines once and returns the `_Features` record; `_line_gap_starts` finds internal whitespace runs of ≥3 columns; `_shared_columns` counts column positions covered by at least `min_rows` rows within a tolerance. This is the `BlockContext` free path, used by the table resolver. |
| `rules.py` | The rule engine. `FeatureThreshold`, `GroupQuota`, `SynergyRule`, `Rule`, `FEATURE_GROUPS` (six orthogonal groups), `RuleEngine` with 24 ordered rules, and the module-level `decide_block` over the `_DEFAULT_ENGINE` singleton. |
| `engine.py` | The driver. `reflow_ascii` runs the whole cascade; `reflow_text` is the text-only convenience form. Private helpers: `_segment` (block grouping), `_classify_block` (first-pass decision), `_decide` (dispatch to the rule engine or the eager features), `_merge_adjacent_prose_decisions`, `_render_block`. |

## The cascade

`reflow_ascii` (`engine.py:342-473`) runs a fixed order:

1. **Mask.** `mask_tagged_tables` then `mask_signature_regions`. Every `<TABLE>` block and every
   signature region is hidden before anything reads the text. The `body_start_line` the caller
   passed is *remapped* into the masked frame by subtracting the newline count of each masked
   span at or before it (`engine.py:356-365`) — without this, the cover boundary computed on
   the unmasked text would point at the wrong line.
2. **Segment.** `_segment` groups consecutive non-blank lines into blocks, breaking on blank
   lines, on `RE_SEPARATOR_LINE` (unless the next line is a numeric cell), and on any line the
   policy calls structural, bulleted, or a checkbox answer (`engine.py:145-180`).
3. **Classify.** Each block gets a first-pass `SpanDecision` from `_classify_block`, which
   consults `decide_block` (the rule engine) and then applies five overrides in order:
   pre-body preservation, bullet-continuation unwrap, `is_tableish_block` tagging,
   front-matter form layout, and `relax_prose_layout_gaps` prose unwrap
   (`engine.py:229-339`).
4. **Resolve.** When `policy.tag_untagged_tables` is set, `resolve_table_regions` from
   `edgar_sec/engine/tables/resolver.py` coalesces the table decisions and re-validates each
   one against the discipline gate (`engine.py:382-399`).
5. **Merge.** `_merge_adjacent_prose_decisions` joins contiguous prose blocks that were split by
   a removable layout boundary, taking the minimum confidence of the pair
   (`engine.py:197-226`).
6. **Render.** For each decision: emit the gap, then the block. `ACTION_UNWRAP` joins non-blank
   lines onto one line under the first line's base indent (`_render_block`, `engine.py:131-142`);
   `ACTION_TAG_AND_PRESERVE` wraps in `<TABLE>`/`</TABLE>` and, for an inferred layout, first
   splits off a narrative intro via `split_structural_table_intro`; `unify_table_prose` may
   rejoin a table to the prose above it at a safe sentence boundary (`engine.py:401-463`).
7. **Restore.** `restore_signature_regions`, then `restore_tagged_tables`, then
   `ensure_table_tag_boundaries` so the restored tags land on standalone lines
   (`engine.py:465-467`).

## Contracts

- **`body_start_line` is required, not optional.** `reflow_ascii` returns `ReflowResult(text)`
  unchanged when `body_start_line is None`, when the text is empty, or when it contains no
  newline (`engine.py:350-351`). A caller that forgets the anchor gets a silent no-op, not an
  error.
- **Pre-body prose is preserved by default.** With `policy.unwrap_pre_body_prose` false (the
  default), any block ending at or before the body start is preserved with
  `("pre_body_region",)` evidence and confidence 1.0 (`engine.py:240-248`).
- **Coordinate honesty is the package's exported responsibility.** `build_line_mapper`
  (`types.py:61-85`) takes the decision list and returns a closure mapping a pre-reflow line
  number to its post-reflow number, accounting only for the lines an `ACTION_UNWRAP` decision
  removed. The only production caller is
  `edgar_sec/engine/forms/normalize.py::_remap_line_anchors`, which uses it to translate the
  cover boundary, body start, and closing span across the reflow and then reports the
  pre-reflow values separately as `cover_boundary_detected_line` / `cover_start_detected_line`.
- **Feature computation is lazy and free until queried.** `BlockContext` uses
  `functools.cached_property` throughout, so a rule that never reads `row_shape_autocorrelation`
  never pays for it. This is v1's "Raw Scalar Invariant / Lazy Memoization" pair preserved.
- **Rules are orthogonal groups, not a flat conjunction.** `FEATURE_GROUPS` names six groups —
  `linguistic_flow`, `interline_wrapping`, `row_dynamics`, `window_density`, `table_geometry`,
  `structural_anchors` — and a `GroupQuota` asks "how many of these fired", so a table is
  recognised by geometry even when its prose markers are absent.
- **Evidence is always populated.** `evaluate_rule` returns a non-empty evidence tuple in every
  branch: the rule's declared `evidence`, or `evidence_builder(ctx)`, or a
  `feature{op}value` string per direct condition (`rules.py:210-218`). `decide` falls back to
  `(rule.name,)` when evidence is empty. `ReflowResult.decisions` is therefore always
  auditable.
- **Confidence is per-decision and lossy by design.** Every absorption or merge takes
  `min(previous.confidence, ...)`, so a region's reported confidence is never better than its
  weakest component.
- **Layer discipline.** `reflow` imports `engine.document.signatures`, `engine.tables.*`, and
  `foundation`; it never imports `pipelines`.

## Public surface

- `reflow_ascii` — the entry point, returning a `ReflowResult` with the decision trace.
  `edgar_sec/engine/reflow/engine.py:342`.
- `reflow_text` — text-only convenience form. `edgar_sec/engine/reflow/engine.py:476`.
- `ReflowPolicy` — the six boolean toggles (`unwrap_pre_body_prose`,
  `split_structural_boundaries`, `split_bullet_items`, `relax_prose_layout_gaps`,
  `unwrap_bullet_continuations`, `tag_untagged_tables`) and six callables
  (`is_checkbox_answer_line`, `is_page_boundary_line`, `is_structural_line`,
  `is_table_bridge_line`, `is_table_tail_line`, `split_table_intro`).
  `edgar_sec/engine/reflow/types.py:20`.
- `SpanDecision` — one block-level action over a half-open line range, with `confidence`,
  `evidence`, and `trace`. `edgar_sec/engine/reflow/types.py:40`.
- `ReflowResult` — `text`, `decisions`, `protected_tables`, `protected_signatures`.
  `edgar_sec/engine/reflow/types.py:52`.
- `ACTION_UNWRAP` / `ACTION_PRESERVE` / `ACTION_TAG_AND_PRESERVE` — the three actions.
  `edgar_sec/engine/reflow/types.py:12-14`.
- `build_line_mapper` — the post-reflow line translator.
  `edgar_sec/engine/reflow/types.py:61`.
- `BlockContext` — the cached scalar feature surface.
  `edgar_sec/engine/reflow/context.py:120`.
- `FINANCIAL_TABLE_BRIDGE_RE` — the fifteen-phrase financial section-label pattern.
  `edgar_sec/engine/reflow/context.py:77`.
- `FeatureSpec` / `FEATURE_REGISTRY` — the 44 calibrated feature specifications.
  `edgar_sec/engine/reflow/registry.py:11` and `:23`.
- `Rule` / `FeatureThreshold` / `GroupQuota` / `SynergyRule` / `FEATURE_GROUPS` /
  `RuleEngine` / `decide_block` — the declarative cascade and its six orthogonal groups.
  `edgar_sec/engine/reflow/rules.py:75`, `:31`, `:55`, `:65`, `:89`, `:143`, `:530`.
- `_compute_features` / `_line_gap_starts` / `_shared_columns` — the eager extractor used by
  the table resolver. `edgar_sec/engine/reflow/features.py:73`, `:34`, `:50`.
- `_MIN_PROSE_ALPHA_DENSITY` — `0.55`, the shared alpha-density floor.
  `edgar_sec/engine/reflow/types.py:16`.

## Tests

- `tests/engine/reflow/test_reflow.py` (140 lines) — covers `reflow_ascii` and
  `_merge_adjacent_prose_decisions` only.

That is the entire test surface. It is one file for six source modules, against the
`AGENTS.md` §6 requirement of one test file per source module.

## Deliberate gaps

- **No direct test for `context.py`, `registry.py`, `rules.py`, or `types.py`.** No file in
  `tests/` imports `RuleEngine`, `FEATURE_GROUPS`, `FEATURE_REGISTRY`, `BlockContext`, or
  `build_line_mapper`. The 44 calibrated `optimal_threshold` values in `registry.py` — which
  carry the empirical weight of v1's research lab — are unverified by the suite. A reader must
  not infer that `unwrap_high_confidence_prose` fires as intended because a prose fixture
  unwrapped correctly in `test_reflow.py`.
- **v1's `defs/text/reflow/classifier.py` (179 loc) was ported, but its `_Features` branch was
  dropped, not replaced.** `classifier.py`'s only export is `_decide`
  (`__all__ = ["_decide"]`, `.v1/defs/text/reflow/classifier.py:179`), and v2's
  `engine.py::_decide` (`engine.py:37`) keeps the first 92 lines byte-identical while dropping
  the trailing 68-line `if features.has_separator or ...` block that computed
  `_shared_columns` over `numeric_cell_rows` / `gap_start_rows`. The dropped work is served
  instead by the `BlockContext` branch of `RuleEngine._default_rules()` — rules
  `preserve_prose_dominant_numeric_alignment`, `tag_preserve_shared_numeric_table`,
  `tag_preserve_separator_grid`, `unwrap_ordinary_prose_no_gaps`, and
  `preserve_layout_gap_candidate` (`rules.py:361-504`). That branch is now unreachable in the
  driver, because `_classify_block` always constructs a `BlockContext`
  (`engine.py:251`). The net effect is that the six v1 reflow modules are **not** a 1:1 port:
  six became five, and the sixth's second half moved into `rules.py`.
- **v1's logical-unit classifier is a different file and it *is* substituted.**
  `.v1/defs/text/structure/logical_units.py` (208 loc, exporting `classify_units`,
  `LogicalUnit`, `units_after`, `line_offset`) had no v2 home. v1 used it in
  `defs/sec_forms/cover/body_start.py:197` and `defs/sec_forms/page_markers/ascii/headers.py:81`
  to know whether a candidate line sat inside a table, list, signature, or TOC unit. v2
  approximates unit context with line-level structural and lexical gates —
  `BlockContext.has_table_wrapper_tag`, `has_checkbox`, `has_dot_leader`, `has_separator_run`,
  `has_signature`, `gutter_4_col_count` — rather than a unit tree. This is recorded as
  "substituted" in `roadmap/refactor_v2/phase_2_5/04_engine_tables_and_forms.md` §4.2. A
  consequence worth naming: v2 has no `LogicalUnit` type, so no caller can ask "what unit is
  line 412 in?"
- **The research lab was dropped, and so were its specifications.** v1's
  `defs/text/reflow/tools/` carried `HYPOTHESES.md` (435 lines) and `RULE_ENGINE_SPEC.md`
  (557 lines) alongside the Parquet export and scikit-learn clustering machinery. Neither
  document has a v2 copy anywhere in the tree (verified: `find . -name RULE_ENGINE_SPEC.md`
  returns only the `.v1` original). The seven `hypothesis_ref` values in `registry.py`
  (`H-GEO-11`, `H-GEO-12`, `H-GEO-13`, `H-GEO-14`, `H-GEO-16`, `H-GEO-17`, `H-GEO-18`) are
  therefore dangling pointers to a document the repository does not contain. Roadmap
  `v2_refactor_roadmap.md` §1.5 Tier 1 commits the lab's relocation to
  `engine/text/reflow/research/`; no such directory exists.
- **v1's `defs/text/bow/` has no v2 home, and this package is not its substitute.** The
  1,234-line tiered bag-of-words engine was replaced by the single-tier Aho-Corasick automaton
  at `edgar_sec/foundation/text/automaton.py` (421 lines, Layer 0), whose
  `LexicalMatcher`/`compile_lexical_matcher` compile one tier per category. The engine-layer
  consumer is `edgar_sec/engine/forms/cover/body_evidence.py`, which scores distinct hits onto
  **v1's same 0-3 scale** through `foundation.text.automaton.tier_confidence`
  (`automaton.py:55-61`: `value >= 3` → 0.9+0.02·hits, `>= 2` → 0.8+0.03·hits, else
  0.45+0.05·hits). `reflow` itself does lexical work with plain regexes and counts
  (`RE_ARTICLE`, `RE_POSSESSIVE`, `FUNCTION_WORDS`, `RE_RELATIVE_PRONOUN` from
  `edgar_sec.foundation.text.grammar`), not with the automaton — so reflow's own feature costs
  are O(text) per feature rather than a single shared pass. See
  `roadmap/refactor_v2/phase_2_5/04_engine_tables_and_forms.md` §4.1.
- **No golden-document regression gate.** Roadmap `v2_refactor_roadmap.md` §1.5 Tier 2 commits
  `testing/goldens/` and `check.py --goldens`; neither exists. `test_reflow.py` uses two inline
  string constants (`PROSE`, `TABLE`), not committed fixtures from `tests/fixtures/`. Zero
  regression on reflow character accuracy across real filings is therefore unverified, which is
  exactly what roadmap milestone M3.5 asks for
  (`roadmap/refactor_v2/phase_2_5/03_engine_document_and_reflow.md:87`) and is still unchecked
  there.
- **No entry point.** No CLI, no `python -m edgar_sec.engine.reflow`. The only production caller
  is `edgar_sec/engine/forms/normalize.py:314`.
- **`page_analysis` is accepted but only its `page_number_runs` attribute is read.**
  `reflow_ascii` takes `page_analysis: object | None` and does
  `bool(getattr(page_analysis, "page_number_runs", ()))` (`engine.py:353`) to set
  `page_context`. A `PageMarkerAnalysis` from
  `edgar_sec/engine/document/page_markers.py` has no such attribute, so passing one always
  yields `page_context=False`. The honest type is a duck-typed object with `page_number_runs`.
- **`_MIN_PROSE_ALPHA_DENSITY` is exported through `__all__` despite the leading underscore.**
  It is a shared constant (`types.py:16`), used by `rules.py:224`, `:466`, `:490`, `:510` and
  `engine.py:122`, `:190`, `:294`, but the leading-underscore naming marks it private by
  convention. It is a real part of the tuning surface; import it from `types`, and expect the
  name to look private.
- **The rules' `line_count` override is a footgun in the other direction.** `decide_block(ctx,
  line_count=...)` lets a caller pass a count that disagrees with `ctx.line_count`, and
  `rules.py:222` short-circuits on it. `_classify_block` always passes
  `len(block_lines)`, which is the non-blank block length, not the raw span length — so a block
  with internal blank lines presents a smaller `line_count` to the cascade than it occupies.
