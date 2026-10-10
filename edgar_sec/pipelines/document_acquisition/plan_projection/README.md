# plan_projection

Layer 4 subpackage for converting published S6 target plans into S9 acquisition work orders.

## Purpose

This package validates the immutable target-plan bundle and projects its targets into the work-order format used to seed an acquisition run.

## Contracts

- **Pinned input**: Projection validates the complete published bundle and does not modify it.
- **Bounded output**: Target rows are streamed into a staged work order; invalid bundles do not yield a usable projection.
- **Run identity**: A projected run is content-derived from the target plan and its schema contracts; an existing run is reused only after integrity validation.

## Deliberate gaps

- **No acquisition execution**: HTTP retrieval, body processing, and snapshot publication are owned by later stages.
