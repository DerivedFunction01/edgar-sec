# `edgar_sec/domain/taxonomy/statements/` — Primary Financial Statement Line Items and Structural Tails

## Purpose

Owns the empirical line-item terms, section transition markers, and structural tail
boundary patterns for the primary financial statements (balance sheet, income
statement, cash flows, stockholders' equity, and section bridges), so a downstream reflow
or table processor can detect statement transitions and closing totals without hardcoding
regexes in parser logic.

## Contracts

- **Deterministic patterns**: Every alternation is compiled by `foundation.regex.builder` (longest-first ordering).
- **Use tail predicates**: Test a line through `is_financial_table_tail_line()`, not by matching term tuples yourself.

## Deliberate gaps

- **No combined statement vocabulary**: Each module owns one statement's terms; callers wanting a spanning vocabulary must compose per-statement tuples.
- **Tail detection is line-prefix based**: `is_financial_table_tail_line()` answers whether a line reads like a closing total; position is `engine/`'s job.
- **Section bridges are not a table family**: `bridge.py` contributes labels and a pattern but no spec.
