# `document_planning`

## Purpose

S6 turns a published filing-catalog plan and an optional pinned inventory snapshot
into an immutable accession-document target plan for later acquisition.

## Contracts

- Planning performs no network access and never mutates catalog or inventory state.
- A filing-catalog plan must use schema 1.3 and declare target-part byte sizes and
  SHA-256 digests. Older plans remain consumable by their existing readers but are
  refused as unpinned S6 scope.
- Inventory-backed plans pin one immutable snapshot ID and verify its lineage and
  relation parts. `current` is resolved once; catalog-only plans require a profile
  whose requests are primary-only.
- Catalog and inventory filing facts must agree. Inventory-backed planning has no
  catalog-locator fallback; an accession absent from the snapshot is recorded as
  `unresolved / accession_not_indexed`.
- Published manifests pin both sources, profile and matcher versions, coverage,
  status totals, and every output part. Reuse requires byte-identical plan content.
- Bundle-sequence and constructed-package rows are candidates, not proof that the
  requested document exists. Planning never starts acquisition.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `inspect` | validate and inspect a plan | `--plan-id`, `[--artifacts]`, `[--json]` |
| `plan` | publish a deterministic target plan | `--catalog-plan`, `[--inventory]`, `[--profile-id]`, `[--auto-primary-profile]`, `[--artifacts]`, `[--json]` |
| `status` | list profiles and published plans | `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# List profiles and published plans
python run.py planning status

# Publish a deterministic plan
python run.py planning plan --catalog-plan plan-2024-01-15 --profile-id primary-docs --inventory

# Inspect a published plan
python run.py planning inspect --plan-id plan-2024-01-15
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
└── document_planning/
    ├── plans/
    │   └── {plan_id}/
    │       └── plan.json
    └── profiles/
        └── {profile_id}.json
```
<!-- AUTOGEN:PATHS:END -->

## Deliberate gaps

- `exact_form` is dropped as a catalog-direct policy. The policy axis collapsed to
  two choices: `submitted_primary` (fast, zero extra requests) and
  `exact_form_with_lazy_index` (verifies the fetched primary; on a confirmed type
  mismatch, fetches `-index.html` only to recover the true form and never again for
  transport failures or missing evidence). The failed-closed `exact_form` mode became
  an awkward middle ground: non-report forms have no inversion risk, and for report
  forms a failure that refuses the exhibit with the index still in reach produced
  worse outcomes than either extreme.
- The baseline profile is generated from the operator or CLI, not inferred from
  inventory observations; users may edit or create additional profiles.
- No source refresh, inventory projection, or acquisition is performed. Operators
  use `inventory project` separately when coverage is missing, then plan from its
  published snapshot.
- Constructed XBRL package URLs are unverified candidates; availability is not
  probed during offline planning.
