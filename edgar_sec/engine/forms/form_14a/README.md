# form_14a

Layer 3: engine/forms/form_14a

## Purpose
Provides review diagnostics over Schedule 14A / 14C proxy and information statement cases generated from acquisition runs. Scores the cover — registrant identity, filing classification, fee-payment boxes — plus Item 1–25 segmentation, voting-proposal headings, and Summary Compensation Table extraction, on top of the shared form analysis.

## Contracts
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic patterns and the shared cover, checkmark, registrant, section, and table machinery without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.
- **Bounded memory execution**: Review case files are read sequentially without accumulating full document bodies in aggregation memory.

## Deliberate gaps
- **No XML extraction**: Schedule 14A/14C has no SEC XML technical specification; analysis runs over the rendered text artifact only.
