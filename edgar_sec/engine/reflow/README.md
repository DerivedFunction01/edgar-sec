# `edgar_sec/engine/reflow` — conservative ASCII reflow and untagged-table tagging

## Purpose

The stage for plain-text (non-HTML) filing content. Segmented blocks get one of three actions
chosen from measured evidence: unwrap a hard-wrapped paragraph, preserve it unchanged, or wrap it
in `<TABLE>` markers without altering a byte inside it. A second pass can promote a bounded run
of numeric rows packed within a block or separated by one blank line when numeric-cell anchors
repeat across enough rows to be a grid rather than a coincidence. A combined `BlockContext` then
applies the shared table and prose rules to the run.

The bias is deliberate and asymmetric. A missed unwrap leaves prose hard-wrapped, which a
reader recovers. A collapsed table corrupts financial data, which nobody recovers. Every
ambiguous block therefore resolves to preserve, and a block that still does not look like a
grid after the boundary resolver has absorbed everything it may absorb is downgraded
rather than tagged.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `types.py` | `ReflowPolicy`, `SpanDecision`, `ReflowResult`, and the `ACTION_*` constants. |
| `features/geometry.py` | `_compute_features` — the single-pass compact feature record the resolver's discipline gate and the rule engine read. |
| `features/context.py` | `BlockContext` — the memoized scalar set every calibrated threshold is defined against. |
| `rules/thresholds.py` | The calibrated feature registry. |
| `rules/cascades.py` | The threshold, quota, and synergy rules, and `decide_block` — measurements to one action. |
| `engine/rewrapper.py` | `reflow_ascii` plus segmentation, classification, generic table row-run discovery, boundary resolution, and rendering. |
| `engine/mapper.py` | `build_line_mapper` — pre-reflow line number to post-reflow line number. |

`features/`, `rules/`, and `engine/` carry their own `README.md`. `__init__.py` is a
docstring per `AGENTS.md` §1.2, so consumers import the leaf:

```python
from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii
from edgar_sec.engine.reflow.types import ReflowPolicy
```

## Contracts

- **The output is a pure function of the stage's inputs.** `reflow_ascii` takes text, a body
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
- **Blank lines alone do not establish a table.** The row-run pass in
  `engine/tables/row_runs.py` requires repeated numeric-cell anchors across a
  minimum run length; compatible label-field drift and aligned nonnumeric
  continuations do not end a run by themselves. The run is then assessed by
  `rules/cascades.py` for the same numeric-table and linguistic-prose evidence used
  on ordinary blocks. Rows may be packed in one block, bridge one blank line, or
  coalesce across a bounded separator/year/subtotal bridge when row evidence resumes
  on both sides. If a confirmed run overlaps a table span already resolved from block
  decisions, the run can merge the contained span or extend it at the overlapping edge;
  an existing span that already contains the run is not wrapped again.
- **Widening a run is preferred to trimming it.** A run that absorbs a classified block or bridges
  a separator, year label, or subtotal can reach a section heading or a footnote legend that no
  geometry test can separate from an index row: `4.  Shareholders' Equity (Deficit)` and
  `3.1  Certificate of Incorporation` parse identically. Trimming such edges back to the
  nearest numeric line was tried and reverted — it deleted genuine exhibit, debt, and equity
  rows and re-emitted overlapping blocks. The residual boundary noise is accepted instead; only
  a future signal that distinguishes a caption from an index row should close it.
- **No stage re-decides or reorders.** Decisions stay ascending and non-overlapping from
  segmentation through rendering, so the decisions a row run overlaps and the spans it
  supersedes are always the ones already in the list.
- **The stage owns no form vocabulary.** Everything that depends on knowing what a checkbox
  answer line or a statement section label looks like arrives on `ReflowPolicy`.

## The policy is the injection seam

`ReflowPolicy` carries the caller-supplied predicates — cover answer lines, page-boundary
lines, cover structural lines, statement bridge labels, statement tail labels — plus
`split_table_intro`. A predicate left `None` contributes nothing to the features that
consult it.

The feature context does not import the cover or financial-taxonomy modules. The caller wires
the predicates instead, as `edgar_sec/engine/forms/normalize.py` does:

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
  — the whole stage (`engine/rewrapper.py`).
- `build_line_mapper(decisions) -> Callable[[int], int]` (`engine/mapper.py`).
- `ReflowPolicy`, `ReflowResult`, `SpanDecision`, the `ACTION_*` constants
  (`types.py`); `BlockContext` (`features/context.py`); `decide_block` and the
  feature registry (`rules/`).

## Command surface

None. Library only.

## Production consumers

- `edgar_sec/engine/forms/normalize.py` — `normalize_document` reflows the ASCII branch
  (representation is not HTML, and `body_start_line > 0`), then re-maps `cover_boundary`,
  `toc_span`, and `body_start` through `build_line_mapper`.
- `edgar_sec/engine/forms/cover/healing/text.py` — `heal_cover_text` reflows the cover
  slice with the same policy minus the bridge and tail callbacks.
- `edgar_sec/engine/tables/resolver.py` — reads `ReflowPolicy` and the computed features to
  grow each confirmed table outward and hold it to the tag discipline gate.

## Mirrored tests

`tests/engine/reflow/` — one test module per source module, including the
`features/`, `rules/`, and `engine/` sub-trees.

## Deliberate gaps

- **No parity harness against a reference implementation.** The mirrored suite is the
  only executable record of the stage's behaviour.
- **No semantic row grammar inference.** The reflow row-run detector uses generic geometry and
  numeric-cell recognition. It does not know that a particular word is a valid header, infer
  arbitrary nonnumeric grids, or guarantee complete capture where headers, subtotals, or rows have
  incompatible layouts.
- **No table pass without a reliable body boundary.** The caller skips ASCII reflow when cover
  analysis cannot supply `body_start_line`; otherwise a candidate row before that boundary is
  excluded from untagged-table promotion.
- **No incremental or resumable pass, and no filesystem, network, or CLI.** A reflow is one
  call over the whole text: no per-block checkpoint, no resume, no streaming.
