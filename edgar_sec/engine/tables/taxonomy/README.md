# `edgar_sec.engine.tables.taxonomy` — multi-zone table classification and shape validation

## Purpose

Scores an extracted 2D grid (`list[list[str]]`) against the declarative family specifications in
Layer 1 (`edgar_sec.domain.taxonomy.tables`) and returns the family it matches, a confidence, and the
evidence behind it. The registered families cover financial statements (income, balance sheet, cash
flow, equity), regulatory disclosure schedules (fair value, lease and debt maturities, pension, EPS
reconciliation, share repurchases), and cover structures.

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

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No offline probe CLI.** The vocabulary census and spec optimizer a developer would use to
  re-fit the registered families are not part of this repository; re-fitting means editing
  `edgar_sec/domain/taxonomy/tables/`.
