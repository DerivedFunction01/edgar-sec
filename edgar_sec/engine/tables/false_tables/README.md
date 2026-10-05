# `engine.tables.false_tables` — layout-grid rejection and prose unwrapping

## Purpose

Rejects layout tables and unwraps their content as readable prose or list text.

## Module → responsibility

| Module | Responsibility |
|---|---|
| `detector.py` | False-table classification for grids and rendered blocks. |
| `unwrapper.py` | Rebuild text from rejected grids and preserve surviving geometry. |

## Contracts

- **A retained table is never rewritten.** The rewrite only removes blocks the detector rejected;
  a retained block is re-emitted as `match.group(0)`. The returned text is `strip()`ped, so
  leading and trailing whitespace of the whole document is not preserved.
- **A rejected grid becomes readable text.** An ordered or bulleted grid becomes one item per line;
  a prose grid becomes joined prose. Consecutive unwrapped blocks join the way the surrounding prose
  would have joined them: a newline between list items so they stay a list, a space between prose
  fragments so they stay a sentence.
- **Geometry follows the text.** Every block the rewrite removes is dropped from the returned
  geometry tuple too, so metadata and text stay in correspondence.
- **The refusal is conservative.** A grid is retained when its second column carries a numeric
  value, when its first column is an `ITEM`/`PART` reference or a TOC row, or when the rendered text
  is a bare numeric separator.

## Public surface

```python
from edgar_sec.engine.tables.false_tables.detector import (
    is_false_grid,
    is_false_table,
)
from edgar_sec.engine.tables.false_tables.unwrapper import (
    cleanup_false_tables_with_metadata,
    unwrap_grid,
)
```

## Command surface

None. Library package, no CLI.

## Mirrored tests

Mirrored coverage lives under `tests/engine/tables/false_tables/`.

## Deliberate gaps

- **Unwrapping without metadata is not exposed.** The public path returns the
  rewritten text with aligned geometry.
- **Known defect:** Without geometry, a rendered table body that still contains
  HTML row/cell tags can be classified as false.
