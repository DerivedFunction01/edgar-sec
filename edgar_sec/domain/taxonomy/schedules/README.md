# `edgar_sec/domain/taxonomy/schedules/` — Supplementary Note Schedules and Statutory Exhibits

## Purpose

Vocabulary, term sets, and `TableFamilySpec` definitions for the supplementary schedules
embedded in SEC filing notes (ASC 260/330/350/360/470/715/740/815/820/842) plus the
statutory exhibit index concepts of Regulation S-K Item 601. Each schedule module pairs
primary and supporting term tuples with a unigram veto list and a compiled evidence pack,
which `domain/taxonomy/tables/families.py` assembles into `FAMILY_SPECS`.

## Layout

| Subpackage / Module | Responsibility |
| :--- | :--- |
| `debt_maturity.py` | ASC 470 debt principal maturities — `DEBT_MATURITY_SPEC` and term sets |
| `deferred_tax.py` | ASC 740 deferred tax assets and liabilities — `DEFERRED_TAX_SPEC` and term sets |
| `eps_reconciliation.py` | ASC 260 earnings-per-share reconciliation — `EPS_RECONCILIATION_SPEC` and term sets |
| `fair_value.py` | ASC 820 fair value hierarchy — `FAIR_VALUE_SPEC` and term sets |
| `intangibles.py` | ASC 350 goodwill and intangible assets — `INTANGIBLES_SPEC` and term sets |
| `inventory.py` | ASC 330 inventory disaggregation and reserves — `INVENTORY_SPEC` and term sets |
| `labor.py` | Labor, collective bargaining, and union representation — `LABOR_CONTRACTS_SPEC`, `IndustryGroup`, `OccupationGroup`, `DYNAMIC_UNION_NAMES` |
| `lease_maturity.py` | ASC 842/840 lease commitments — `LEASE_MATURITY_SPEC` and term sets |
| `legal.py` | ASC 450 legal proceedings and contingencies — term sets only, no spec |
| `pension.py` | ASC 715 retirement benefits — `PENSION_SPEC` and term sets |
| `ppe.py` | ASC 360 property, plant and equipment — `PPE_SPEC` and term sets |
| `shares_purchased.py` | Regulation S-K Item 703 issuer repurchases — `SHARES_PURCHASED_SPEC` and statutory phrases |
| `stock_comp.py` | ASC 718 rollforward — `STOCK_COMP_ROLLFORWARD_SPEC`, term sets, `STOCK_COMP_TAIL_RE` |
| `tax_reconciliation.py` | ASC 740 rate reconciliation — `TAX_RECONCILIATION_SPEC` and term sets |
| `derivatives/` | ASC 815/220: `spec.py` holds `DERIVATIVES_HEDGING_SPEC` and `AOCI_SPEC`; `aoci`, `bases`, `cp`, `credit`, `eq`, `fx`, `ir`, `generic`, `guards` hold instrument vocabularies; `engine.py` is the shared combinator engine |
| `compensation/stock_comp.py` | ASC 718 term tuples and `STOCK_COMP_TAIL_RE` without a spec |
| `statutory/exhibits.py` | Item 601 index phrases, canonical headers, `RE_EXHIBIT_NUMBER`, `RE_EXHIBIT_STATUTORY_PHRASE` |

## Contracts

- **Layer-1 purity:** zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`. Upward edges go only to `edgar_sec.foundation` and, downward, to
  `domain/taxonomy/tables/` for the spec and shape types.
- **Deterministic alternations:** every compiled alternation goes through
  `foundation.regex.builder.build_alternation`. `legal.py` instead uses
  `foundation.text.compounds` to expand its variants and compounds.
- **Every schedule declares a unigram veto list** (usually `("activities",)`) so a family
  cannot claim a line that belongs to another. `legal.py` publishes
  `LEGAL_UNIGRAM_VETOES` directly rather than a spec.
- **Compensation is a leaf, not a spec owner.** `compensation/stock_comp.py` exists to give
  `statements/predicates.py` a `STOCK_COMP_TAIL_RE` without pulling in the
  `TableFamilySpec` machinery; `stock_comp.py` at the package root carries the same terms
  plus the spec.

## Public surface

| Symbol | Module |
| :--- | :--- |
| `<AREA>_PRIMARY_TERMS`, `<AREA>_SUPPORTING_TERMS`, `<AREA>_VETOES`, `<AREA>_SPEC` for debt maturity, deferred tax, EPS reconciliation, fair value, intangibles, inventory, labor, lease maturity, pension, PP&E, stock compensation, tax reconciliation | the corresponding root module |
| `SHARES_PURCHASED_STATUTORY_PHRASES`, `CANONICAL_REPURCHASE_HEADERS`, `SHARES_PURCHASED_SPEC` | `shares_purchased.py` |
| `LEGAL_ALL_TERMS`, `LEGAL_LITIGATION_TERMS`, `LEGAL_PROCEEDING_TERMS`, `LEGAL_CONTINGENCY_TERMS`, `LEGAL_PARTY_COURT_TERMS`, `LEGAL_COMPETITOR_TERMS`, `LEGAL_UNIGRAM_VETOES` | `legal.py` |
| `DERIVATIVES_PRIMARY_TERMS`, `DERIVATIVES_CONTEXT_TERMS`, `DERIVATIVES_VETOES`, `DERIVATIVES_HEDGING_SPEC`, `AOCI_PRIMARY_TERMS`, `AOCI_SECONDARY_TERMS`, `AOCI_SPEC` | `derivatives/spec.py` |
| `IR_DERIVATIVE_TERMS`, `FX_DERIVATIVE_TERMS`, `EQUITY_DERIVATIVE_TERMS`, `CREDIT_DERIVATIVE_TERMS`, `COMMODITY_DERIVATIVE_TERMS`, `GENERIC_DERIVATIVE_TERMS`, `ASC_815_MASTER_DISCLOSURES`, `CROSS_ASSET_STRUCTURES`, `DERIVATIVE_HEADING_TERMS`, `NON_DERIVATIVE_EXCLUSIONS` | `derivatives/{ir,fx,eq,credit,cp,generic,guards}.py` |
| `STOCK_COMP_PRIMARY_TERMS`, `STOCK_COMP_SUPPORTING_TERMS`, `STOCK_COMP_TAIL_TERMS`, `STOCK_COMP_TAIL_RE`, `STOCK_COMP_VETOES` | `stock_comp.py` and `compensation/stock_comp.py` |
| `EXHIBIT_INDEX_STATUTORY_PHRASES`, `CANONICAL_EXHIBIT_HEADERS`, `RE_EXHIBIT_NUMBER`, `RE_EXHIBIT_STATUTORY_PHRASE` | `statutory/exhibits.py` |
| The 17 names `derivatives/__init__.py` re-exports from its child modules | `derivatives/` |

No command surface.

## Tests

```text
tests/domain/taxonomy/schedules/compensation/test_stock_comp.py
tests/domain/taxonomy/schedules/statutory/test_exhibits.py
```

## Deliberate gaps

- **Two mirrored tests for twenty-seven modules.** Only `compensation/stock_comp.py` and
  `statutory/exhibits.py` have one. `AGENTS.md` §6.3 requires a test file per source
  module at the mirrored path; the other 25 modules, including every schedule spec that
  `FAMILY_SPECS` depends on, are asserted only indirectly through
  `tests/domain/taxonomy/tables/test_specs.py`.
- **Nine of the fourteen root schedule modules declare no `__all__`.** Their public symbols
  are still importable; only the export list is absent. The five that do (`intangibles`,
  `inventory`, `labor`, `legal`, `ppe`) list theirs.
- **`stock_comp.py` and `compensation/stock_comp.py` are near-duplicates.** Their term
  tuples and their compiled `STOCK_COMP_TAIL_RE` pattern are equal today, and the root
  module additionally carries `STOCK_COMP_ROLLFORWARD_SPEC`. `tables/families.py` imports
  the root module; `statements/predicates.py` imports the compensation one. No test pins the
  two to each other, so drift would be silent — and a leaf module shadowed by a sibling of
  the same name is exactly the kind of duplication `AGENTS.md` §1.1 exists to prevent.
- **`derivatives/__init__.py` is a barrel re-export.** It imports 17 names from its child
  modules and republishes them in `__all__`, which `AGENTS.md` §1.2 forbids for
  `__init__.py`. It is the only such barrel in this layer.
- **Derivatives and exhibit index have no algorithmic consumer in this layer.** The
  classification that reads these specs is `engine/tables/taxonomy/classifier.py`; the
  exhibit regexes are matched by engine-side cover logic. Nothing in `domain/` composes
  them into a decision.