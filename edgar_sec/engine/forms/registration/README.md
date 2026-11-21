# registration

Layer 3: engine/forms/registration

## Purpose
Provides analytical diagnostics, boundary metrics, and checkmark validation over registration review cases generated from acquisition runs (Form S-1 by default; S-3, S-4, and S-8 ride the same analyzer). Evaluates facing-sheet checkmark states, prospectus body transition boundaries, and statutory Part I/II Item coverage across large-scale review corpora.

## Contracts
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic AST models, regex patterns, and compiled lexical automata without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.
- **Per-case isolation of bodies**: Each case's text is loaded whole for its own analysis and released with the case report; aggregation receives case reports, not document bodies.

## Deliberate gaps
- **Ad-hoc table extraction**: HTML tables in Form S-1 filings are normalized to standard ASCII grids; dedicated exhibit parsing is deferred to downstream specialized extractors.
