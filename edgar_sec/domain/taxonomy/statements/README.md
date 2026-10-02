# `edgar_sec/domain/taxonomy/statements/` — Primary Financial Statement Line Items and Structural Tails

## Purpose

Owns the empirical line-item terms, section transition markers, and structural tail
boundary patterns for the five primary financial statements (balance sheet, income
statement, cash flows, stockholders' equity, and section bridges), so a downstream reflow
or table processor can detect statement transitions and closing totals without hardcoding
regexes in parser logic.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `balance.py` | Asset/liability/equity/cash term sets, `BALANCE_SHEET_TAIL_TERMS`, `BALANCE_SHEET_TAIL_RE`, `BALANCE_SHEET_VETOES`, `BALANCE_SHEET_SPEC` |
| `bridge.py` | `FINANCIAL_BRIDGE_TERMS`, `FINANCIAL_TABLE_BRIDGE_RE` |
| `cash_flow.py` | Operating/investing/financing term sets, `CASH_FLOW_ACTIVITIES_TRIO`, tail terms and regex, vetoes, `CASH_FLOW_SPEC` |
| `equity.py` | Primary/supporting equity term sets, tail terms and regex, vetoes, `EQUITY_STATEMENT_SPEC` |
| `income.py` | Revenue, cost-of-sales, gross-profit, operating-expense, operating-income and EPS term sets, tail terms and regex, vetoes, `INCOME_STATEMENT_SPEC` |
| `predicates.py` | `is_financial_table_bridge_line(line)`, `is_financial_table_tail_line(line)` |

## Contracts

- **Layer-1 purity:** zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`. Upward edges go only to `edgar_sec.foundation`, and downward to
  `domain/taxonomy/schedules/compensation/stock_comp.py` for its tail pattern.
- **Deterministic regexes:** every compiled alternation goes through
  `foundation.regex.builder.build_alternation` with `auto_escape=True`,
  `flexible_whitespace=True`, and `compact=True`.
- **No shims and no barrel re-exports:** each leaf module exports its own symbols via
  `__all__`; consumers import from the leaf module.
- **`predicates.py` is the intended Layer 3 entry point.** It is the only module here that
  exposes behaviour rather than data, and it exists so the engine can test a line without
  importing five keyword dictionaries. Its tail predicate consults the five statement tail
  patterns *plus* `STOCK_COMP_TAIL_RE`, so a stock-compensation rollforward tail is a
  financial table tail.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `ASSETS_TERMS`, `LIABILITIES_TERMS`, `EQUITY_TERMS`, `CASH_TERMS`, `BALANCE_SHEET_TAIL_TERMS`, `BALANCE_SHEET_TAIL_RE`, `BALANCE_SHEET_VETOES`, `BALANCE_SHEET_SPEC` | `balance.py` |
| `FINANCIAL_BRIDGE_TERMS`, `FINANCIAL_TABLE_BRIDGE_RE` | `bridge.py` |
| `OPERATING_ACTIVITIES_TERMS`, `INVESTING_ACTIVITIES_TERMS`, `FINANCING_ACTIVITIES_TERMS`, `CASH_FLOW_ACTIVITIES_TRIO`, `CASH_FLOW_TAIL_TERMS`, `CASH_FLOW_TAIL_RE`, `CASH_FLOW_VETOES`, `CASH_FLOW_SPEC` | `cash_flow.py` |
| `EQUITY_PRIMARY_TERMS`, `EQUITY_SUPPORTING_TERMS`, `EQUITY_STATEMENT_TAIL_TERMS`, `EQUITY_STATEMENT_TAIL_RE`, `EQUITY_VETOES`, `EQUITY_STATEMENT_SPEC` | `equity.py` |
| `REVENUE_TERMS`, `COST_OF_SALES_TERMS`, `GROSS_PROFIT_TERMS`, `OPERATING_EXPENSES_TERMS`, `OPERATING_INCOME_TERMS`, `EPS_TERMS`, `INCOME_STATEMENT_TAIL_TERMS`, `INCOME_STATEMENT_TAIL_RE`, `INCOME_STATEMENT_VETOES`, `INCOME_STATEMENT_SPEC` | `income.py` |
| `is_financial_table_bridge_line(line: str) -> bool`, `is_financial_table_tail_line(line: str) -> bool` | `predicates.py` |

No command surface.

## Tests

```text
tests/domain/taxonomy/statements/test_balance.py
tests/domain/taxonomy/statements/test_bridge.py
tests/domain/taxonomy/statements/test_cash_flow.py
tests/domain/taxonomy/statements/test_equity.py
tests/domain/taxonomy/statements/test_income.py
tests/domain/taxonomy/statements/test_predicates.py
```

## Deliberate gaps

- **The table-family specs here are consumed elsewhere, not here.** `BALANCE_SHEET_SPEC`,
  `CASH_FLOW_SPEC`, `EQUITY_STATEMENT_SPEC`, and `INCOME_STATEMENT_SPEC` are assembled into
  `FAMILY_SPECS` by `domain/taxonomy/tables/families.py` and read by
  `engine/tables/taxonomy/classifier.py`. `bridge.py` has no spec, because a section bridge
  is a transition marker rather than a standalone table.
- **No unistring or combined statement vocabulary.** Each module owns one statement's
  terms; there is no shared "financial statement" super-table, and the only cross-statement
  composition happens in `predicates.py`'s tail tuple.
- **Multi-zone table classifier specs are not deferred to Phase 3 — they exist.** The
  earlier version of this README said `TableFamilySpec`, `EvidenceTier`, `ShapeConstraint`,
  and `RepairPolicy` were Phase 3 work; all four are implemented today under
  `domain/taxonomy/tables/`. What is still absent is the v1 *probe CLI* for table
  classification.
- **Tail detection is line-prefix based, not layout based.** `is_financial_table_tail_line`
  answers whether a line reads like a closing total; it does not know whether that line is
  in the last row of a table. Deciding position is `engine/`'s job.