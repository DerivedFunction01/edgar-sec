# form_15

Layer 3: engine/forms/form_15

## Purpose
Provides review diagnostics over Form 15 deregistration notice cases generated from acquisition runs. Scores the single-page cover — commission file number, registrant identity, rule provisions relied upon, holder count — and the conformed signature block, on top of the shared form analysis.

## Contracts
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic regex patterns and the shared cover, checkmark, registrant, and signature machinery without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.
- **Bounded memory execution**: Review case files are read sequentially without accumulating full document bodies in aggregation memory.

## Deliberate gaps
- **No XML extraction**: Form 15 has no SEC XML technical specification; analysis runs over the rendered text artifact only.
