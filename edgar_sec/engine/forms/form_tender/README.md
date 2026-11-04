# form_tender

Layer 3: engine/forms/form_tender

## Purpose
Provides review diagnostics over tender offer statement cases generated from acquisition runs. Scores the schedule facing sheet — subject company, filing persons, class title, CUSIP, notice contact, transaction designation boxes — plus per-kind item coverage and offer-document companion signals, on top of the shared form analysis.

## Contracts
- **Kind before taxonomy**: The document kind is classified from the form code line and the cover face; section detection runs on that kind's own item set, never on a merged union.
- **Deterministic scoring**: All case analysis and summary metrics derive strictly from deterministic patterns and the shared cover, checkmark, and CUSIP machinery without stochastic heuristics.
- **Fail-safe case isolation**: An individual corrupted or unparseable review case produces structured anomaly records rather than interrupting run aggregation.

## Deliberate gaps
- **Companions are signals only**: Offer to purchase and letter of transmittal documents are EX-99 exhibits; their presence is recorded from the primary's exhibit references and their content is never parsed here.
