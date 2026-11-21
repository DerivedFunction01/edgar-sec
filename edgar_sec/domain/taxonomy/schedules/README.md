# `edgar_sec/domain/taxonomy/schedules/` — Compensation Tail Terms and Statutory Exhibit Index Concepts

## Purpose

Two vocabularies: the ASC 718 compensation term tuples in `compensation/stock_comp.py`,
consumed by the statement tail predicates in `domain/taxonomy/statements/predicates.py`,
and the statutory exhibit index concepts of Regulation S-K Item 601 in
`statutory/exhibits.py`, consumed by the reflow context features.

## Contracts

- **Deterministic patterns**: Every alternation is compiled by `foundation.regex.builder` (longest-first ordering).
- **Compensation terms have one owner**: `compensation/stock_comp.py` holds the ASC 718 term tuples and the tail pattern built from them; consumers import from there rather than restating terms.

## Deliberate gaps

- **Exhibit indexes are a vocabulary without a family**: `statutory/exhibits.py` publishes terms and patterns but no `TableFamilySpec`.
