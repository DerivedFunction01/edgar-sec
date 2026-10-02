# `edgar_sec.engine.tables.taxonomy` — multi-zone table classification and shape validation

## Purpose

Scores an extracted 2D grid (`list[list[str]]`) against the declarative family specifications in
Layer 1 (`edgar_sec.domain.taxonomy.tables`) and returns the family it matches, a confidence, and the
evidence behind it. Twenty-two families are registered, covering financial statements (income,
balance sheet, cash flow, equity), regulatory disclosure schedules (fair value, lease and debt
maturities, pension, EPS reconciliation, share repurchases), and cover structures.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `shapes.py` | `validate_shape(grid, constraint, *, in_scope=False)` — row-count, column-count, and numeric-density checks against a `ShapeConstraint`, using `is_numeric_cell`. |
| `context.py` | `SectionContext`, `CoverScope`, `TocReference`, `TableNode`, `TableContext`, `ContextEvidence`, `ContextSource`. |
| `classifier.py` | `classify_table(grid, *, section_context=None, candidate_families=None)` — the zone evaluator and exclusion vetoes. |

There is no `__init__.py`; the sub-modules import each other by absolute path.

## Contracts

- **Layer 3 isolation.** Imports downward from Layer 1 (`domain.taxonomy.tables`) and Layer 0
  (`foundation.text.evidence`). Never Layer 4 or Layer 5.
- **Zone routing.** Header rows are the first two (`grid[:2]`); body rows are the rest. Preceding
  neighbor blocks and the section heading come from the optional `SectionContext` and can boost an
  otherwise ambiguous intrinsic score.
- **Exclusion vetoes are absolute.** An exclusion hit in any evaluated zone disqualifies the family
  immediately — no amount of geometric plausibility recovers it.
- **Fail-open.** A missing `SectionContext` is a valid state and falls back to standalone
  classification against every registered family.

## Public surface

```python
from edgar_sec.engine.tables.taxonomy.classifier import classify_table
from edgar_sec.engine.tables.taxonomy.context import SectionContext
from edgar_sec.engine.tables.taxonomy.shapes import validate_shape
```

`classify_table` returns a `FamilyClassification` (`family`, `confidence`, `evidence`,
`structural_confirmed`, `repair_policy`, `tags`, `all_matches`). `validate_shape` returns
`(ok, reason)`, where `reason` is a machine-readable string such as `empty_grid` or
`row_count_3_below_min_5`.

## Command surface

None. Library package, no CLI.

## Mirrored tests

`tests/engine/tables/taxonomy/test_classifier.py` (24 tests). Only `classifier.py` has a mirrored
test file; `shapes.py` and `context.py` are exercised transitively.

## Deliberate gaps

- **No production consumer.** `classify_table` has no caller outside this package, so it is a
  prepared classification core rather than a wired capability. Nothing in `engine/forms/normalize.py`
  or the `documents run` pipeline invokes it.
- **No offline probe CLI.** The vocabulary census and spec optimizer under
  `.v1/defs/taxonomy/probe/` are V1 developer tools and are deliberately not ported.
- **`TableNode` and `TableContext` are unused.** They describe a structure index no V2 component
  builds yet. `classify_table` takes a bare grid and an optional `SectionContext`; nothing
  constructs the per-table context for it.