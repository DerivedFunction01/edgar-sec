# `edgar_sec/engine/forms/cover/tables` — form-governed cover table cleaning

Unwraps cover-only pseudo-tables, strictly inside the verified cover boundary.

## Purpose

Generic layout tables are unwrapped upstream by
`edgar_sec.engine.tables.false_tables`. This package handles the tables that are
only unwrappable because the filing's own form says so — chiefly the annual /
quarterly / transition report-period checkbox block — and it refuses to touch
anything outside the cover.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `cleaner.py` | `clean_cover_tables` and its raw-text classifier. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

## Contracts

- Only tables whose start tag occurs before `boundary.end_line` are evaluated.
  Exhibit indices and financial statements are never inspected.
- Classification is always performed against the raw `<TABLE>` block text, never
  against geometry rows from a prior render pass. Geometry left behind by an
  upstream unwrapping step may belong to a completely different table, and
  classifying against it misclassifies the address table that follows.
- **Geometry is paired by the stable `TableGeometry.table_index` attribute, not
  by position in the tuple.** Positional pairing is unreliable once an upstream
  pass has evicted unwrapped tables; surviving geometries keep their original
  IDs. Unwrapping uses the geometry only as a rendering hint.
- With `enabled_cleaners=()`, with `boundary.end_line is None`, or when the text
  contains no `<TABLE>`, the call is an exact no-op: the same string object and
  the same geometries tuple come back.
- A boundary whose `end_line` exceeds the line count is treated as covering the
  whole document rather than raising.

## Public surface

- `clean_cover_tables(text, boundary, table_geometries=(), *, enabled_cleaners=("report_period",)) -> tuple[str, tuple[TableGeometry, ...]]` — `cleaner.py`.

## Command surface

None. Library package, no CLI.

## Tests

- `tests/engine/forms/cover/tables/test_cleaner.py`

## Deliberate gaps

- **One cleaner.** `report_period` is the only entry `enabled_cleaners` accepts.
  The parameter exists so the caller can switch it off without a code change;
  it is not a registry.
- **No ASCII-only tables without `<TABLE>` markers are unwrapped.** A cover
  rendered as plain indented rows is left for the reflow and healing stages.
- **`TableSpan` masking is not used here.** `apply_cover_checkmark_decisions`
  masks and restores tagged tables around its own rewrite; this module operates
  on the full text and reasons in the original frame throughout.
