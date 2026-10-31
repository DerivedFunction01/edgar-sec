# registration

Layer 3: engine/forms/registration

## Purpose
Provides analytical diagnostics, boundary metrics, and checkmark validation over Form S-1 review cases generated from acquisition runs. Evaluates facing-sheet checkmark states, prospectus body transition boundaries, and statutory Part I/II Item coverage across large-scale review corpora.

## Contracts
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic AST models, regex patterns, and compiled lexical automata without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.
- **Bounded memory execution**: Review case files are streamed sequentially without accumulating full document bodies in aggregation memory.

## Deliberate gaps
- **Ad-hoc table extraction**: HTML tables in Form S-1 filings are normalized to standard ASCII grids; dedicated exhibit parsing is deferred to downstream specialized extractors.
