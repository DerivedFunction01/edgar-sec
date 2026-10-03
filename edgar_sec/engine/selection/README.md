# `edgar_sec/engine/selection` — quota-driven, family-capped target selection

Answers the question deterministic planning cannot: not "which rows match these filters"
but "which rows best fill a declared quota profile, without letting one corporate family or one
form crowd out the rest".

## Purpose

Planning can define quotas and a company-family cap, then select a deterministic subset that
respects them where possible. `features.py` builds the input snapshot; `selector.py` returns the
selection and coverage report. The family signature vocabulary is `CLASSIFICATION_DIMENSIONS`,
and `max_per_company_classification` controls its cap.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `policy.py` | Quota policy, seed vocabulary, construction, and validation. |
| `features.py` | Feature snapshot construction and filing-form/date dimensions. |
| `source.py` | Candidate reads from published snapshots. |
| `selector.py` | Quota selection and coverage report. |
| `inventory.py` | Advisory quota-feasibility statistics. |

## Contracts

- **Selection is network-free and deterministic.** The same snapshot, policy, and seed
  produce the same result.
- **Parent selections and mandatory seeds participate in quota coverage.** Duplicate
  parent keys are rejected, and mandatory seeds are retained.
- **`company_family` derives from the catalog's registrant profiles.** A seed set is a
  mandatory-filer list and does not define corporate identity.
- **Candidate SQL binds values and validates dimensions.** Policy construction rejects
  unknown dimensions and retired fields, and result mapping raises on schema drift rather
  than truncating rows.
- **Feature snapshots are content-addressed and reused** when their inputs match.
- **Selection is bounded and scoped.** Candidate access takes explicit limits and uses a
  scoped in-memory session.
- **Layer discipline** follows `AGENTS.md`; this package does not import pipelines.

## Command surface

None. Library package, no CLI.

## Public surface

- `SelectionPolicy`, `EraBand`, and seed/policy helpers — `policy.py`.
- `FeatureSnapshotBuilder`, `SnapshotPaths`, and dimension helpers — `features.py`.
- `CandidateSource`, `CandidateFilters` — `source.py`.
- `DeficitSelector`, `SelectionResult` — `selector.py`.
- `InventoryStatistics` — `inventory.py`.

## Mirrored tests

Mirrored coverage lives under `tests/engine/selection/`.

## Deliberate gaps

- **Snapshot identity does not cover the derivation algorithm.** A change to a dimension's
  derivation rules can resolve to an existing snapshot directory, so such a change requires
  clearing that directory or changing a hashed input.
- **Size banding is anchored to `form_family` alone,** not to form family within an era.
- **`foreign_status` is a domestic/foreign classification,** not a country-grade value.
- **`state_of_incorporation` and `state_of_business` cannot be stratified on.** They are
  carried by the snapshot but are not selectable dimensions.
- **This package does not own the corpus.** It reads published catalog artifacts and cannot
  fetch data or locate its own inputs without caller-supplied paths.
- **Share caps are a fill-time constraint, not an invariant of `SelectionResult`.**
  `_violates_cap` runs during weighted pool fill. Seed, composite, floor, and
  form-era allocation stages accept candidates through `_record`, which consults
  the signature cap but not `policy.caps`; mandatory seeds explicitly bypass the
  signature cap. Read `report["underfilled_floors"]` alongside the realised
  `coverage_distributions`, which is what `_build_report` publishes.
- **No rebalancing pass.** Underfilled floors are recorded rather than resolved by
  exchanging an already-selected candidate.
- **Feasibility is advisory, never a gate.** Published feasibility statistics do not block a
  plan, and they do not account for competition between floors, caps, and seeds.
- **No form-name validation against a vocabulary.** An unrecognized form name is accepted and
  yields an empty snapshot rather than an error.
- **No plan writer, provenance, or work order.** This package returns selection values;
  publication belongs to the pipeline layer.
- **The selection report is an untyped mapping** with no schema or version field.
