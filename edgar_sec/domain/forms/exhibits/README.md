# exhibits

Declarative exhibit authority coverage, profiles, and pack registry for Layer 1 domain.

## Purpose

The `exhibits` package provides a unified source-qualified code ledger for Regulation S-K Item 601 and Form 20-F exhibit items. It defines exhibit authority profiles and implements a pack lookup seam that returns `None` until packs are activated in D4.

## Contracts

- **Source-qualified identity**: Every coverage entry is identified by `(authority_id, code)` tuples.
- **Zero I/O**: No file reads, network calls, or regex compilation.
- **No barrel re-exports**: Import directly from leaf modules.
- **Unactivated rows**: All coverage entries return `None` from `resolve_pack_for_identity()` in D1.

## Deliberate gaps

- **Form 20-F disabled**: All Form 20-F coverage rows have `coverage_status="disabled"`.
- **No active NLP packs**: Layer 1 contains no text parsing or heuristics.
- **Exhibit authority only**: Primary form profiles are defined in their respective family packages (`families/annual/`, `families/quarterly/`, `families/current/`).
