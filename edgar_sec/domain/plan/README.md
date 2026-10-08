# edgar_sec.domain.plan

Provides the universal `PlanEnvelope` contract and generic filesystem discovery for published plan manifests across pipelines.

## Module Layout

| Module | Responsibility |
|---|---|
| `envelope.py` | Minimal `PlanEnvelope` mapping wrapper requiring a non-empty `plan_id`. |
| `discovery.py` | Generic filesystem plan bundle discovery (`read_plan_envelope`, `discover_plans`). |

## Guarantees & Contracts

- **Minimal Invariant**: Any directory holding a readable `plan.json` with a non-empty `plan_id` constitutes a valid plan.
- **Payload Agnostic**: Does not enforce or inspect pipeline-specific keys; all fields remain accessible via `Mapping` access.
- **Deterministic Sort**: Discovered plans are sorted by directory modification time descending, with `plan_id` breaking ties.

## Public Surface

- `edgar_sec.domain.plan.envelope.PlanEnvelope`
- `edgar_sec.domain.plan.discovery.read_plan_envelope`
- `edgar_sec.domain.plan.discovery.discover_plans`

## Command Surface

None (pure domain model and reader).

## Mirrored Tests

- `tests/domain/plan/test_envelope.py`
- `tests/domain/plan/test_discovery.py`

## Deliberate Gaps

- **No Pipeline Schemas**: Pipeline-specific fields (e.g. catalog forms, chunk sizes, registries) belong to their owning pipeline specializations, not here.
