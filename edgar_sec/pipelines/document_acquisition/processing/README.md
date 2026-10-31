# processing

Layer 4 per-target document processing and run coordination.

## Purpose

Validates acquired-body evidence, executes the selected document operations as part of the acquisition run, and records bounded processing results.

## Contracts

- **Pinned input**: Processing uses the request and selected body committed by the acquisition work order and run state.
- **Bounded IO**: Source reads and derived outputs are subject to the configured processing budget.
- **Deterministic results**: Operation identities and result manifests are content-pinned.
- **Retry ownership**: The acquisition run lock spans each target's acquisition and processing; operation retries preserve completed results and receipts.

## Deliberate gaps

- **Partial operation support**: Non-identity transforms remain unsupported until their handlers and budgets are available.
