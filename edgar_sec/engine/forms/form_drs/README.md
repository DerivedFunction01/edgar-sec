# form_drs

Layer 3: engine/forms/form_drs

## Purpose
Provides review diagnostics over confidential draft registration (DRS) cases. Scores the wrapper itself — the confidential banner, the base-form signal read from the document face, and the dispatch of the body to that base form's own profile and taxonomy — plus metadata extraction for the DRSLTR correspondence variant, on top of the shared form analysis.

## Contracts
- **No DRS taxonomy**: The wrapper owns no item set; section detection for a submission body runs on the dispatched base family's taxonomy, exactly as the base form's own review would.
- **Dispatch is face-read**: The base form comes from the document face (the draft-submission title or the base cover's form line), never from the submission's other documents.
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic patterns and the shared machinery without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.

## Deliberate gaps
- **Confidential posture is recorded, not handled**: The banner is scored as filed; no redaction or sealing behaviour is modelled, because filed DRS content is public as filed after the fact.
