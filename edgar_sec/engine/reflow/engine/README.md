# `edgar_sec/engine/reflow/engine` — the reflow stage and the line mapper

## Purpose

The last mile. `rewrapper.py` is the whole stage: mask, project the body boundary, segment,
decide, resolve table boundaries, merge, render, restore. `mapper.py` translates a decision
trace recorded against the source into the coordinate frame of the output.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `rewrapper.py` | `reflow_ascii` plus `_render_block`, `_segment`, `_is_bullet_prose_block`, `_merge_adjacent_prose_decisions`, `_classify_block`, `_masked_body_start`. |
| `mapper.py` | `build_line_mapper` — pre-reflow line number to post-reflow line number. |

`__init__.py` is a docstring per `AGENTS.md` §1.2. Consumers import the leaf:

```python
from edgar_sec.engine.reflow.engine.mapper import build_line_mapper
from edgar_sec.engine.reflow.engine.rewrapper import reflow_ascii
```

## Contracts

- **Output is a pure function of the stage's inputs.** `text`, `body_start_line`,
  `page_analysis`, `policy`. No clock, no filesystem, no randomness; the same input yields
  the same text and the same decision tuple, and that is a tested property.
- **An existing `<TABLE>` block is never reclassified or rewritten.** It is masked before any
  analysis and restored byte-for-byte after rendering.
  `ReflowResult.protected_tables` and `.protected_signatures` report what was found.
- **The body boundary is projected, not reused.** `_masked_body_start` subtracts, for every
  span that ends at or before the boundary, the number of newlines that span removed, and for
  a span that straddles the boundary, the number of lines before it. Using the raw boundary
  against masked lines mis-places every block after the first table.
- **The pre-body region is a refusal, not a heuristic.** With `unwrap_pre_body_prose` false,
  any block ending at or before `body_start_line` resolves to preserve with evidence
  `("pre_body_region",)`.
- **A table's narrative is unwrapped, not preserved inside the grid.** When a decision is
  tagged and its evidence is `inferred_table_layout`, the block is first split by the
  policy's `split_table_intro` (or the structural default), and the narrative part is
  rendered as an unwrap. A cue the splitter does not recognise leaves the narrative inside the
  table, which is legible; a false cue would strip a financial line out of its table, which
  is not.
- **Prose is only reunited at a boundary that cannot change a column.** `unify_table_prose`
  requires a lowercased first character, no negative boundary phrase, no sentence terminal on
  the preceding line, and adjacent decisions that are neither tagged nor protected.
- **Page-marker context only annotates evidence.** A decision under `page_analysis` gains
  `"page_boundary_context"` in its evidence; its action is unchanged.
- **Tags are put on their own lines.** `ensure_table_tag_boundaries` normalises a restored
  `<TABLE>` so `prefix <TABLE>` becomes `prefix\n<TABLE>` with the span's bytes untouched.

## `build_line_mapper`

Only `ACTION_UNWRAP` changes the line count, so the mapping is a set of downward shifts
applied from each unwrap decision's `end_line` onward, answered by binary search in
`O(log k)` for `k` unwrap decisions.

A line *inside* a collapsed range reports its own source index rather than the index of the
single line it was absorbed into. That is exact for the trace the mapper exists to translate:
every decision boundary is either the first line of an unwrap block, which the output keeps
at that index, or at or after a prior `end_line`. Interior lines of a collapsed block have no
distinct output line to name.

## Public surface

- `reflow_ascii(text, *, body_start_line, page_analysis=None, policy=None) -> ReflowResult`.
- `build_line_mapper(decisions) -> Callable[[int], int]`.

## Command surface

None. This is a library package with no CLI.

## Production consumers

- `edgar_sec/engine/forms/normalize.py` — `normalize_document`, on the ASCII branch
  (representation is not HTML, and `body_start_line > 0`).
- `edgar_sec/engine/forms/cover/healing/text.py` — `heal_cover_text`, on the cover slice.

## Tests

Mirrored coverage lives under `tests/engine/reflow/engine/`.

## Deliberate gaps

- **The cover-healing reflow branch is not reached in production.** `heal_cover_text` only
  reflows when `reflow_prose=True`, and its sole caller `normalize_document` passes
  `reflow_prose=False`. The code path is live and tested; nothing exercises it today.
- **`split_table_intro` cannot be disabled.** A caller that supplies `None` gets the
  structural default rather than "do not split". Suppressing the split entirely is not
  expressible.
- **No incremental or resumable pass.** A reflow is one call over the whole text. There is
  no per-block checkpoint, no resume, and no streaming; a multi-megabyte filing is processed
  as one string.
- **No `PageMarkerAnalysis` construction.** `page_analysis` is read for `page_number_runs`
  and nothing else; building one belongs to `engine/document/page_markers/`.
- **No coverage accounting in the result.** `ReflowResult` carries text, decisions, and the
  two protected-region lists — not the lines before and after the body boundary, and not a
  count of what the resolver absorbed. A caller wanting that must read the decision evidence.
- **No reference-implementation parity harness.** The mirrored suite above is the only executable
  record.