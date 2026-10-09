# `edgar_sec/domain/taxonomy/schedules/` — Supplementary Note Schedules and Statutory Exhibits

## Purpose

Vocabulary, term sets, and `TableFamilySpec` definitions for the supplementary schedules
embedded in SEC filing notes (ASC 260/330/350/360/470/715/740/815/820/842) plus the
statutory exhibit index concepts of Regulation S-K Item 601. Each schedule declares its
terms, its exclusions, and its 2D shape; the family specs are assembled into
`FAMILY_SPECS` by `tables/families.py`.

## Contracts

- **Deterministic patterns:** every alternation is compiled by
  `foundation.regex.builder`, so branches stay longest-first and a caller adding a
  term cannot introduce a shorter branch that shadows a longer one.
- **The compensation terms have one owner.** `compensation/stock_comp.py` holds the
  ASC 718 term tuples and the closing-total pattern, and `stock_comp.py` builds
  `STOCK_COMP_ROLLFORWARD_SPEC` on those same terms, so the table family and the
  statement tail predicate cannot drift apart.
- **Exclusions are advisory, not a partition.** Whether a given area's veto terms
  reach its evidence pack is a per-module question, so read the pack rather than
  assuming two areas are mutually exclusive — see
  [the tables README](../tables/README.md).

## Deliberate gaps

- **Legal proceedings and exhibit indexes are vocabularies without a family.**
  `legal.py` and `statutory/exhibits.py` publish terms, phrases, and headers but no
  `TableFamilySpec`, so `FAMILY_SPECS` has no entry for either: a caller classifying
  a legal-proceedings table or an Item 601 exhibit index gets no family from this
  registry and must match on the terms directly.
