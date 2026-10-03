# `edgar_sec/domain/taxonomy/schedules/` — Supplementary Note Schedules and Statutory Exhibits

## Purpose

Vocabulary, term sets, and `TableFamilySpec` definitions for the supplementary schedules
embedded in SEC filing notes (ASC 260/330/350/360/470/715/740/815/820/842) plus the
statutory exhibit index concepts of Regulation S-K Item 601. Each schedule declares its
terms, its exclusions, and its 2D shape; the family specs are assembled into
`FAMILY_SPECS` by `tables/families.py`.

## Layout

| Subpackage / Module | Responsibility |
| :--- | :--- |
| `debt_maturity.py` | ASC 470 debt principal maturities |
| `deferred_tax.py` | ASC 740 deferred tax assets and liabilities |
| `eps_reconciliation.py` | ASC 260 earnings-per-share reconciliation |
| `fair_value.py` | ASC 820 fair value hierarchy |
| `intangibles.py` | ASC 350 goodwill and intangible assets |
| `inventory.py` | ASC 330 inventory disaggregation and reserves |
| `labor.py` | Labor, collective bargaining, and union representation |
| `lease_maturity.py` | ASC 842/840 lease commitments |
| `legal.py` | ASC 450 legal proceedings and contingencies — term sets only |
| `pension.py` | ASC 715 retirement benefits |
| `ppe.py` | ASC 360 property, plant and equipment |
| `shares_purchased.py` | Regulation S-K Item 703 issuer repurchases |
| `stock_comp.py` | ASC 718 rollforward family spec, built on the shared compensation terms |
| `tax_reconciliation.py` | ASC 740 rate reconciliation |
| `compensation/stock_comp.py` | The shared ASC 718 term tuples and closing-total pattern |
| `derivatives/` | ASC 815/220: per-asset-class instrument vocabularies, a shared combinator, and the two family specs in `spec.py` |
| `statutory/exhibits.py` | Regulation S-K Item 601 index phrases and canonical headers |

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

## Public surface

- One `<AREA>_SPEC` per area above that has one, together with its primary and
  supporting term tuples, closing-total pattern, and exclusions — the corresponding
  module.
- Regulation S-K Item 601 index phrases and canonical headers —
  `statutory/exhibits.py`.
- The ASC 815 hedging and AOCI family specs and their terms — `derivatives/spec.py`.

No command surface.

## Tests

Tests mirror this package under `tests/domain/taxonomy/schedules/`.

## Deliberate gaps

- **Legal proceedings and exhibit indexes are vocabularies without a family.**
  `legal.py` and `statutory/exhibits.py` publish terms, phrases, and headers but no
  `TableFamilySpec`, so `FAMILY_SPECS` has no entry for either: a caller classifying
  a legal-proceedings table or an Item 601 exhibit index gets no family from this
  registry and must match on the terms directly.
