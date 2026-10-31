# `edgar_sec/domain/taxonomy/schedules/` — Supplementary Note Schedules and Statutory Exhibits

## Purpose

Vocabulary, term sets, and `TableFamilySpec` definitions for the supplementary schedules
embedded in SEC filing notes (ASC 260/330/350/360/470/715/740/815/820/842) plus the
statutory exhibit index concepts of Regulation S-K Item 601. Each schedule declares its
terms, its exclusions, and its 2D shape; the family specs are assembled into
`FAMILY_SPECS` by `tables/families.py`.

## Contracts

- **Deterministic patterns**: Every alternation is compiled by `foundation.regex.builder` (longest-first ordering).
- **Compensation terms have one owner**: `compensation/stock_comp.py` holds ASC 718 term tuples; `stock_comp.py` builds specs from those same terms.
- **Exclusions are advisory**: Whether veto terms reach evidence packs is a per-module question; orthogonality is best-effort.

## Deliberate gaps

- **Legal proceedings and exhibit indexes are vocabularies without a family**: `legal.py` and `statutory/exhibits.py` publish terms but no `TableFamilySpec`.
