# `document_planning`

## Purpose

S6 turns a published filing-catalog plan and an optional pinned inventory snapshot
into an immutable accession-document target plan for later acquisition.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `paths.py` | Profile, plan, and source-contract path resolution. |
| `schemas.py` | Target-plan schema/version and inventory relation contracts. |
| `profiles.py` | Profile discovery, validation, normalization, and matching rules. |
| `catalog_scope.py` | Pinned, digest-verified reading of catalog-plan occurrences. |
| `inventory_evidence.py` | Pinned inventory lineage and bounded accession evidence streaming. |
| `matching.py` | Role matching and SEC locator safety checks. |
| `planner.py` | Source pinning, coverage, plan identity, and streamed target generation. |
| `publication.py` | Atomic, immutable plan-bundle publication and exact reuse checks. |
| `discovery.py` | Manifest-only discovery and full bundle validation. |
| `cli.py` | Direct offline command parsing and dispatch. |
| `operator.py` | Explicit evidence-mode selection and default-no publication flow. |
| `commands/` | Plan, inspect, and status handlers. |

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

## Public surface

Use [`planner.create_document_plan()`](planner.py) to build a plan and
[`discovery.read_published_plan()`](discovery.py) to validate/read one. Profiles are
JSON files under `policies/document_targets/`; their shape and normalization rules
are owned by [`profiles.py`](profiles.py).

## Command surface

Run `python run.py planning status`, `python run.py planning plan`, or
`python run.py planning inspect`. The direct CLI is offline; the interactive
operator asks for evidence mode and requires default-no consent before publication.
See [`commands/README.md`](commands/README.md) for the handler boundary.

Published plans live at
`{artifacts_root}/document_planning/plans/<plan_id>/plan.json`, with target parts
under form partitions. There is no mutable `current` pointer for plans.

## Mirrored tests

`tests/pipelines/document_planning/`.

## Deliberate gaps

- No built-in target profile is selected for an operator; profiles are curated inputs.
- No source refresh, inventory projection, or acquisition is performed. Operators
  use `inventory project` separately when coverage is missing, then plan from its
  published snapshot.
- Constructed XBRL package URLs are unverified candidates; availability is not
  probed during offline planning.
