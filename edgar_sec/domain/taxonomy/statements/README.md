# `edgar_sec/domain/taxonomy/statements/` — Primary Financial Statement Line Items and Structural Tails

## Purpose

Owns the empirical line-item terms, section transition markers, and structural tail
boundary patterns for the primary financial statements (balance sheet, income
statement, cash flows, stockholders' equity, and section bridges), so a downstream reflow
or table processor can detect statement transitions and closing totals without hardcoding
regexes in parser logic.

## Contracts

- **Deterministic patterns:** every alternation is compiled by
  `foundation.regex.builder`, so branches stay longest-first and a caller adding a
  term cannot introduce a shorter branch that shadows a longer one.
- **Test a line through the predicates**, not by matching the term tuples yourself.
  The tail predicate unions every statement's closing-total pattern with the ASC 718
  compensation rollforward's, so a stock-compensation closing balance counts as a
  financial table tail.

## Deliberate gaps

- **No combined statement vocabulary.** Each module owns one statement's terms and
  there is no shared "financial statement" super-table, so a caller wanting one
  vocabulary spanning statements must compose the per-statement tuples.
- **Tail detection is line-prefix based, not layout based.**
  `is_financial_table_tail_line()` answers whether a line reads like a closing total;
  it cannot tell you whether that line is in the last row of a table. Deciding
  position is `engine/`'s job.
- **Section bridges are not a table family.** `bridge.py` contributes labels and a
  pattern but no spec, so `FAMILY_SPECS` has no bridge entry and no classification
  can name a section bridge as its own family.
