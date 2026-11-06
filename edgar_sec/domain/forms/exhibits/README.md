# exhibits

Declarative exhibit authority coverage, profiles, and pack registry for Layer 1 domain.

## Purpose

The `exhibits` package provides a source-qualified code ledger, authority profiles, declarative candidate packs, and an authority/code lookup for Regulation S-K Item 601, Form 20-F, and Regulation AB. Lookup returns a declared pack where one is mapped and its coverage status is candidate or partial; the body evaluator in `engine/forms/plugins/exhibit_selection.py` consumes the packs.

## Contracts

- **Source-qualified identity**: Every coverage entry is identified by `(authority_id, code)` tuples.
- **Zero I/O**: No file reads, network calls, or regex compilation.
- **No barrel re-exports**: Import directly from leaf modules.
- **Declarative lookup only**: A registry match identifies candidate evidence data; it does not classify a document or assert measured accuracy.

## Deliberate gaps

- **Form 20-F disabled**: All Form 20-F coverage rows have `coverage_status="disabled"`.
- **No body evaluator in Layer 1**: Layer 1 contains source-backed pack declarations only; text parsing, scoring, and assessment runtime live in `engine/forms/plugins/exhibit_selection.py`.
- **No holdout evidence**: The packs have no labeled issuer/accession-separated evaluation corpus or measured error rates; activation remains gated on fixture-backed review and recorded acceptance.
- **Exhibit authority only**: Primary form profiles are defined in their respective family packages.
