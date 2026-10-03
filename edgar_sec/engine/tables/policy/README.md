# `edgar_sec/engine/tables/policy` — where a table's narrative ends

## Purpose

The generic ASCII reflow coordinator knows what a block of lines looks like. The modules here know
what a *table* looks like: where the sentence introducing a grid stops and the grid starts, and
whether the block after a grid is that row's wrapped continuation or the next paragraph.

Both judgements are conservative in the same direction. An unrecognised intro cue leaves the
narrative inside the table, which a reader recovers. A false cue strips a financial line out of its
table, which nobody recovers.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `intro.py` | `split_structural_table_intro`, `is_tableish_block`, `unify_table_prose`. |
| `continuation.py` | `is_table_row_continuation`. |

`__init__.py` is a docstring per `AGENTS.md` §1. Consumers import the leaf:

```python
from edgar_sec.engine.tables.policy.continuation import is_table_row_continuation
from edgar_sec.engine.tables.policy.intro import split_structural_table_intro
```

## Contracts

- **An intro split needs a cue *and* geometry.** `split_structural_table_intro` looks only at the
  first non-blank line: it must end in sentence punctuation or match `TABLE_INTRO_CUE_RE`, or the
  whole block is returned unsplit. Even then it only splits before a line carrying two or more wide
  column gaps, or a tab plus alphabetic content.
- **A cue the vocabulary does not hold is never guessed at.** The cue set lives in
  `../patterns.py`; filing-specific prose such as *"The fair value was estimated using
  assumptions"* is not in it, so it stays inside the table.
- **A table-shaped block is recognised before prose relaxation may unwrap it.**
  `is_tableish_block` answers on geometry alone: at least one column gap, a tab, or a shared numeric
  column, *and* a separator with enough rows — or three numeric rows under two shared columns.
- **A continuation is a positional claim, not a topical one.** A wrapped row description carries no
  numeric cells, so the only evidence is that its numbers land under columns the previous rows
  already established: two cells within three columns of an established position decides it outright,
  and one aligned cell needs every remaining word to be numeric or a total keyword.
- **A page-boundary line refuses continuation when the policy says so.** That is what stops a page
  marker being absorbed into a table.
- **Reuniting prose requires a safe boundary on both sides.** The preceding line must not end in
  sentence punctuation, the following line must start lowercased and must not match
  `NEGATIVE_BOUNDARY_RE`, and its first token must be longer than one character or be the article
  `a`. Neither neighbour may be a tagged table, and neither side may contain a protected-table
  sentinel.

## Public surface

- `split_structural_table_intro(lines) -> (narrative, table_lines)`.
- `is_tableish_block(features) -> bool`.
- `unify_table_prose(decisions, blocks, decision_index, skip_decision_indices, group) -> tuple[str, ...] | None`.
- `is_table_row_continuation(previous, continuation, policy=None) -> bool`.

## Command surface

None. Library package, no CLI.

## Production consumers

- `edgar_sec/engine/reflow/engine/rewrapper.py` — `split_structural_table_intro` and
  `unify_table_prose` in the render loop, `is_tableish_block` in `_classify_block`.
- `edgar_sec/engine/tables/resolver.py` — `is_table_row_continuation` in the forward sweep.

## Tests

- `tests/engine/tables/policy/test_intro.py`
- `tests/engine/tables/policy/test_continuation.py`

## Deliberate gaps

- **No policy is threaded into the intro predicates.** `split_structural_table_intro`,
  `is_tableish_block`, and `unify_table_prose` have no `policy` parameter, so a caller cannot supply
  its own intro vocabulary at this level. The reflow stage reaches them through
  `ReflowPolicy.split_table_intro`, which is the substitutable seam.
- **`is_tableish_block` reads its argument with `getattr` and a default.** It accepts any object
  exposing the fields it needs, which is how both the compact `_Features` record and the full
  `BlockContext` satisfy it. It is not typed to either, and a record missing a field reads as `0` or
  `False` rather than raising.
- **No row-level or cell-level policies.** These modules judge whole blocks and whole row groups.
  Whether a specific column is a currency, a fiscal year, or a percentage is
  `engine/tables/numeric_cells.py` and `domain/taxonomy/statements/`, read here but not
  re-implemented.
- **Two guards are far more permissive than their names suggest.** `NEGATIVE_BOUNDARY_RE` is
  compiled with `re.IGNORECASE`, so `Item \d+`, `Part [IVX]+`, `Co-Registrants:`, and
  `Securities\s+registered` all fire on a lowercase line and are compatible with the
  start-lowercased requirement. Likewise `is_table_row_continuation` only applies its
  sentence check on the single-aligned-cell path. Both are retained as written rather than tightened,
  because tightening them is a product-behaviour change.