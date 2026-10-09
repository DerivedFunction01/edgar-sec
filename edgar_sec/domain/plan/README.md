# edgar_sec.domain.plan

Provides the universal `PlanEnvelope` contract and generic filesystem discovery for published plan manifests across pipelines.

## Guarantees & Contracts

- **Minimal Invariant**: Any directory holding a readable `plan.json` with a non-empty `plan_id` constitutes a valid plan.
- **Payload Agnostic**: Does not enforce or inspect pipeline-specific keys; all fields remain accessible via `Mapping` access.
- **Deterministic Sort**: Discovered plans are sorted by directory modification time descending, with `plan_id` breaking ties.

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

None (pure domain model and reader).

## Deliberate Gaps

- **No Pipeline Schemas**: Pipeline-specific fields (e.g. catalog forms, chunk sizes, registries) belong to their owning pipeline specializations, not here.
