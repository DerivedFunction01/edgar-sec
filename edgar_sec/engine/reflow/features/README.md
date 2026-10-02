# `edgar_sec/engine/reflow/features` — block measurement

## Purpose

Two views of the same block of ASCII lines. Neither decides anything: the rule cascade in
`../rules/` reads these measurements and decides, and the table boundary resolver in
`../../tables/resolver.py` reads only the compact record.

The split is what keeps the stage affordable. A reflow pass evaluates the cascade many times
against candidate blocks, most of which it rejects, and the resolver's discipline gate runs
on every grown span. `geometry.py` answers both questions the resolver asks — does this block
have column geometry, and do its numeric cells line up under columns other rows share — in
one pass. `context.py` computes the full memoized feature set, on first access and cached on
the instance.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `context.py` | `BlockContext` — the 44 registered features plus the derived properties the rules read directly, memoized per instance. |
| `geometry.py` | `_Features`, `_compute_features`, `_line_gap_starts`, `_shared_columns`, `_numeric_cell_starts` — the single-pass compact record. |

`__init__.py` is a docstring per `AGENTS.md` §1.2. Consumers import the leaf:

```python
from edgar_sec.engine.reflow.features.context import BlockContext
from edgar_sec.engine.reflow.features.geometry import _compute_features
```

## Contracts

- **A gap is an internal run of three or more spaces.** Leading indentation is never a gap:
  indented prose and list items are exactly the blocks a reflow is allowed to unwrap, so
  `_line_gap_starts` starts after the first content character.
- **A column is shared when enough rows place a gap or a cell within tolerance of the same
  position.** `_shared_columns` takes `min_rows` and a one-character tolerance and counts an
  anchor once, so two positions inside the tolerance are one column. Both callers pass
  `min_rows=3`, for gaps and for numeric cells.
- **Properties are computed once per instance.** `BlockContext` carries `__dict__` and uses
  `cached_property`; a second access returns the same object.
- **Two features are the caller's, not the text's.** `has_checkbox` and `is_financial_bridge`
  consult `ReflowPolicy` rather than importing a form family or a statement taxonomy. See
  `../README.md` for the policy wiring and
  `test_context.py::test_has_checkbox_uses_the_injected_predicate` for a case that
  distinguishes the injected answer from the mark vocabulary's.
- **The mark vocabulary is checked first, and it is not optional.** A block containing a
  checkmark is a checkbox block whether or not a predicate was supplied; the predicate can
  only add evidence, never remove it.
- **The geometry record is a single pass.** `_compute_features` visits each line once and
  answers all twelve fields, including the shared-column count, which is derived from the
  collected row positions rather than a second scan.

## Public surface

- `BlockContext(text_or_lines, policy=None)` — `raw_text`, `raw_lines`, `non_blank_lines`,
  `line_count`, the 44 registered features, the derived properties the rules read
  (`alpha_density`, `max_gap`, `shared_numeric_columns`, `cell_edge_aligned_count`,
  `stub_gutter_numeric_count`, and the rest), and `to_feature_dict()` / `to_feature_floats()`.
- `_Features` — the twelve-field compact record: `non_blank`, `has_structural`, `has_tab`,
  `has_separator`, `has_dot_leader`, `has_signature`, `max_gap`, `gap_start_rows`,
  `numeric_cell_rows`, `shared_numeric_columns`, `alpha_density`, `any_lowercase`.
- `_compute_features(lines) -> _Features`.
- `_line_gap_starts(line) -> tuple[int, ...]`,
  `_shared_columns(cell_rows, *, min_rows, tolerance=1) -> int`, `_numeric_cell_starts`.

## Command surface

None. This is a library package with no CLI.

## Production consumers

- `../rules/cascades.py` — `decide_block` over a `BlockContext`; `_decide` over either.
- `../engine/rewrapper.py` — `_classify_block` and `_is_bullet_prose_block`.
- `../../tables/resolver.py` — `_compute_features` for the tag discipline gate.

## Tests

- `tests/engine/reflow/features/test_context.py` (37)
- `tests/engine/reflow/features/test_geometry.py` (19)

`test_context.py` pins both the measurements and the injection seam, including a test that
reads this module's own source to assert it imports no form family — the seam is a claim
about an import graph, and a unit test is the only thing that keeps it true as modules move.

## Deliberate gaps

- **`_Features.numeric_cell_rows` is annotated `int` and holds a tuple.** A reference-tree
  annotation bug, carried over unchanged: the runtime value is a tuple of per-row cell
  positions and every consumer calls `len()` on it. Fixing the annotation alone is a one-word
  change.
- **`_numeric_cell_starts` is a private alias of a public helper.** `geometry.py` rebinds
  `numeric_cell_starts` from `engine/tables/tokens.py`, and
  `engine/tables/policy/continuation.py` binds the same helper under the same private name.
  It is an alias for readability, not a wrapper.
- **No serialisation to disk and no vector store.** `to_feature_dict` and `to_feature_floats`
  are in-memory; there is no artifact, no schema version, and no persistence.
  `to_feature_floats` returns a `tuple[float, ...]` rather than an array deliberately, so
  numpy never enters the import graph of a process that merely normalizes a filing.
- **`BlockContext` does not measure prose *quality*.** It measures density, layout, grammar
  markers, and column geometry. Whether a block reads as prose is a judgement the rule cascade
  makes, not a feature this module publishes.