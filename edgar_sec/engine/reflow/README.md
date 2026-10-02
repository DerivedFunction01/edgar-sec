# `edgar_sec/engine/reflow` — conservative ASCII reflow and untagged-table tagging

## Purpose

The stage for plain-text (non-HTML) filing content. Segmented blocks get one of three actions
chosen from measured evidence: unwrap a hard-wrapped paragraph, preserve it unchanged, or wrap it
in `<TABLE>` markers without altering a byte inside it. A second pass can promote a bounded run
of numeric rows packed within a block or separated by one blank line when numeric-cell anchors
repeat across at least three rows. A combined `BlockContext` then applies the shared table and
prose rules to the run.

The bias is deliberate and asymmetric. A missed unwrap leaves prose hard-wrapped, which a
reader recovers. A collapsed table corrupts financial data, which nobody recovers. Every
ambiguous block therefore resolves to preserve, and a block that still does not look like a
grid after the boundary resolver has absorbed everything it may absorb is downgraded
rather than tagged.

`features/` measures a block, `rules/` turns the measurements into one action,
`engine/rewrapper.py` segments, decides, resolves table boundaries, and renders, and
`engine/mapper.py` translates the resulting source-frame trace into the output frame.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `types.py` | `ReflowPolicy`, `SpanDecision`, `ReflowResult`, the three `ACTION_*` constants, and `_MIN_PROSE_ALPHA_DENSITY`. |
| `features/geometry.py` | `_Features`, `_compute_features`, `_line_gap_starts`, `_shared_columns`, `_numeric_cell_starts` — the single-pass compact record the resolver's discipline gate reads. |
| `features/context.py` | `BlockContext` — the memoized scalar set every calibrated threshold is defined against, plus the two serialization methods. |
| `rules/thresholds.py` | `FeatureSpec`, `FEATURE_REGISTRY` (44 calibrated features), `_register`. |
| `rules/cascades.py` | `FeatureThreshold`, `GroupQuota`, `SynergyRule`, `Rule`, `FEATURE_GROUPS`, `RuleEngine`, `decide_block`, `_decide`. |
| `engine/rewrapper.py` | `reflow_ascii` plus segmentation, classification, generic table row-run discovery, boundary resolution, and rendering. |
| `engine/mapper.py` | `build_line_mapper` — pre-reflow line number to post-reflow line number. |

`features/`, `rules/`, and `engine/` carry their own `README.md`. `__init__.py` is a
docstring per `AGENTS.md` §1.2, so consumers import the leaf:

```python
from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy
```

## Contracts

- **The output is a pure function of four inputs.** `reflow_ascii` takes text, a body
  boundary, an optional page analysis, and an optional policy. No clock, no filesystem, no
  randomness; the same input yields the same text and the same decision tuple
  (`tests/engine/reflow/engine/test_rewrapper.py::test_decisions_are_deterministic`).
- **An already-tagged table is byte-for-byte protected.** `mask_tagged_tables` runs before
  any analysis and `restore_tagged_tables` after rendering, so a reflow can neither
  reclassify nor rewrite a `<TABLE>` span. Signature blocks are masked the same way through
  `mask_signature_regions`.
- **No decision is ever made above the body boundary unless asked.** With
  `unwrap_pre_body_prose` false (the default), every block ending at or before
  `body_start_line` resolves to preserve with evidence `("pre_body_region",)`.
- **The body boundary is projected into the masked frame.** Masking removes the newlines
  inside a protected span, so `body_start_line` is translated by how many lines each span
  removed ahead of it before segmentation. Using the raw boundary against masked lines
  mis-places every block after the first table.
- **Only `ACTION_UNWRAP` changes the line count.** Every other action emits its lines
  unchanged, which is what makes `build_line_mapper` a shift table rather than a reindex.
- **Blank lines alone do not establish a table.** The table row-run pass in
  `engine/tables/row_runs.py` requires repeated numeric-cell anchors across at least three rows;
  compatible label-field drift and aligned nonnumeric continuations do not end a run by themselves.
  The run is assessed by `rules/cascades.py` for the same numeric-table and linguistic-prose evidence
  used on ordinary blocks. Rows may be packed in one block, bridge one blank line, or coalesce across
  a bounded separator/year/subtotal bridge when row evidence resumes on both sides.
  If a confirmed run overlaps a table span already resolved from block decisions, the run can
  merge the contained span or extend it at the overlapping edge; an existing span that already
  contains the run is not wrapped again.
- **Widening a run is preferred to trimming it.** A run that absorbs a classified block or bridges
  a separator, year label, or subtotal can reach a section heading or a footnote legend that no
  geometry test can separate from an index row: `4.  Shareholders' Equity (Deficit)` and
  `3.1  Certificate of Incorporation` parse identically. An earlier revision pulled such edges
  back to the nearest numeric line and regressed 73 of 79 reviewed documents — it deleted genuine
  exhibit, debt, and equity rows and re-emitted overlapping blocks. The residual boundary noise is
  accepted instead; only a future signal that distinguishes a caption from an index row should
  close it.

- **The stage is single-pass over the decision list.** Blocks are ascending and non-overlapping,
  so the decisions a run overlaps are found by binary search rather than a scan, and the spans a
  run supersedes all fall inside that same window. The window is spliced once per accepted run
  instead of rebuilding the whole list, and the resolver locates the blocks a decision covers
  through an indexed lookup that memoises the block it returns, because a growing span re-reads the
  same block. This is equivalence-preserving: a per-document sha256 over all 800 cohort documents
  matches the pre-optimisation output exactly.

  On a fixed 40-document sample, interleaving the two arms to cancel machine drift, the
  pre-optimisation tree takes 13.84/13.87/14.01s against 12.91/12.96/12.98s — about 7% faster,
  median per document 178ms to 166ms, worst document 4.73s to 4.44s.

  An earlier measurement of this change claimed 37%. It compared against a baseline that was not a
  faithful reconstruction of the pre-optimisation sources, and the figure does not reproduce. The
  numbers above are the ones to trust.

  Carrying a start-line list alongside the decisions to avoid rebuilding it per run was measured
  and rejected. The gain was inside run-to-run noise, and it would add a parallel-list invariant
  that desyncs silently if a splice is ever missed — the same class of bug that duplicated table
  bodies when a run boundary moved.
- **The stage owns no form vocabulary.** Everything that depends on knowing what a checkbox
  answer line or a statement section label looks like arrives on `ReflowPolicy`.

## The policy is the injection seam

`ReflowPolicy` carries five caller-supplied predicates — cover answer lines, page-boundary
lines, cover structural lines, statement bridge labels, statement tail labels — plus
`split_table_intro`. A predicate left `None` contributes nothing to the features that
consult it.

This is not a stylistic preference. In the reference tree the feature context imported the
cover and financials reflow modules directly, which put two upward edges inside the engine.
In V2 the caller wires them, as `edgar_sec/engine/forms/normalize.py:229` does:

```python
ReflowPolicy(
    unwrap_pre_body_prose=True,
    relax_prose_layout_gaps=True,
    unwrap_bullet_continuations=True,
    is_checkbox_answer_line=is_checkbox_answer_line,  # engine.forms.cover.reflow
    is_page_boundary_line=is_page_marker_line,  # engine.document.page_markers.detector
    is_structural_line=is_cover_layout_line,  # engine.forms.cover.reflow
    is_table_bridge_line=is_financial_table_bridge_line,  # domain.taxonomy.statements
    is_table_tail_line=is_financial_table_tail_line,  # domain.taxonomy.statements
)
```

`is_financial_table_bridge_line` is read through the `is_table_bridge_line` field, which is
also what the boundary resolver passes to `is_structural_table_bridge`. A caller that
supplies a different bridge predicate changes both, consistently.

## Public surface

- `reflow_ascii(text, *, body_start_line, page_analysis=None, policy=None) -> ReflowResult`
  — the whole stage.
- `build_line_mapper(decisions) -> Callable[[int], int]`.
- `ReflowPolicy`, `ReflowResult`, `SpanDecision`, the three `ACTION_*` constants.
- `BlockContext`, `_Features`, `_compute_features`.
- `RuleEngine`, `decide_block`, `FEATURE_GROUPS`, `FEATURE_REGISTRY`, `FeatureSpec`,
  `Rule`, `GroupQuota`, `SynergyRule`, `FeatureThreshold`.

## Command surface

None. Library only.

## Production consumers

- `edgar_sec/engine/forms/normalize.py:239` — `normalize_document` reflows the ASCII branch
  (representation is not HTML, and `body_start_line > 0`), then re-maps `cover_boundary`,
  `toc_span`, and `body_start` through `build_line_mapper`.
- `edgar_sec/engine/forms/cover/healing/text.py:67` — `heal_cover_text` reflows the cover
  slice with the same policy minus the bridge and tail callbacks.
- `edgar_sec/engine/tables/resolver.py` — reads `ReflowPolicy` and `_compute_features` to
  grow each confirmed table outward and hold it to the tag discipline gate.

## Tests

- `tests/engine/reflow/test_types.py` (8)
- `tests/engine/reflow/features/test_geometry.py` (19)
- `tests/engine/reflow/features/test_context.py` (37)
- `tests/engine/reflow/rules/test_thresholds.py` (119)
- `tests/engine/reflow/rules/test_cascades.py` (46)
- `tests/engine/reflow/engine/test_rewrapper.py` (56)
- `tests/engine/reflow/engine/test_row_run_promotion.py` (6)
- `tests/engine/reflow/engine/test_mapper.py` (7)

## Deliberate gaps

- **No parity harness against the reference tree.** Byte parity with V1 was tracked by a
  differential script that is not part of this repository; nothing here re-runs it. The
  mirrored suite above is the only executable record of the stage's behaviour.
- **`_decide`'s `_Features` branch has no production caller.** `_classify_block` always
  builds a `BlockContext` unless a caller passes an explicit `features=` record, which no
  production path does. It is retained as the cascade's documented geometry-only fast path.
- **`_Features.numeric_cell_rows` is annotated `int` and holds a tuple.** A reference-tree
  annotation bug, carried over unchanged because the runtime value is what the cascade and
  the discipline gate read; every consumer calls `len(...)` on it. The annotation is wrong,
  not the value.
- **No `PageMarkerAnalysis` construction.** `reflow_ascii` reads
  `page_analysis.page_number_runs`; it does not build one. Page-marker detection belongs to
  `engine/document/page_markers/`.
- **No semantic row grammar inference.** The reflow row-run detector uses generic geometry and
  numeric-cell recognition. It does not know that a particular word is a valid header, infer
  arbitrary nonnumeric grids, or guarantee complete capture where headers, subtotals, or rows have
  incompatible layouts.
- **No table pass without a reliable body boundary.** The caller skips ASCII reflow when cover
  analysis cannot supply `body_start_line`; otherwise a candidate row before that boundary is
  excluded from untagged-table promotion.
- **No incremental or resumable pass, and no filesystem, network, or CLI.** A reflow is one
  call over the whole text: no per-block checkpoint, no resume, no streaming.
