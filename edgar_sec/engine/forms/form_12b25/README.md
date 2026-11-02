# form_12b25

Layer 3: engine/forms/form_12b25

## Purpose
Provides review diagnostics over Form 12b-25 notification cases generated from acquisition runs. Scores the subject-report selection, Part I registrant block, Part II relief checkboxes, Part III narrative, Part IV contact and Yes/No answers, and the signature block, on top of the shared form analysis.

## Contracts
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic regex patterns and the shared cover, checkmark, section, registrant, and signature machinery without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.
- **Bounded memory execution**: Review case files are read sequentially without accumulating full document bodies in aggregation memory.

## Deliberate gaps
- **No XML extraction**: Form 12b-25 has no SEC XML technical specification; analysis runs over the rendered text artifact only.
