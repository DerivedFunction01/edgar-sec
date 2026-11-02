# form_11k

Layer 3: engine/forms/form_11k

## Purpose
Provides review diagnostics over Form 11-K employee stock purchase, savings and similar plan annual report cases generated from acquisition runs. Scores the cover — commission file number, plan title, issuer name, report-type boxes — plus item segmentation and the conformed signature block, on top of the shared form analysis.

## Contracts
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic patterns and the shared cover, checkmark, registrant, section, and signature machinery without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.
- **Bounded memory execution**: Review case files are read sequentially without accumulating full document bodies in aggregation memory.

## Deliberate gaps
- **No XML extraction**: Form 11-K has no SEC XML technical specification; analysis runs over the rendered text artifact only.
- **No bespoke financial-statement extraction**: plan financial statements ride the shared segmentation only; the Step 16 ruling and its evidence are recorded in the master plan.
