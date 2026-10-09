# edgar_sec.domain.plan

Provides the universal `PlanEnvelope` contract and generic filesystem discovery for published plan manifests across pipelines.

## Contracts

- **Minimal invariant**: Any directory holding a readable `plan.json` with non-empty `plan_id` constitutes a valid plan.
- **Payload agnostic**: Does not enforce or inspect pipeline-specific keys.
- **Deterministic sort**: Discovered plans are sorted by directory modification time descending, with `plan_id` breaking ties.

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

None (pure domain model and reader).

## Deliberate gaps

- **No pipeline schemas**: Pipeline-specific fields belong to their owning pipeline specializations.
