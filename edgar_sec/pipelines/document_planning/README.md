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
| `plan` | publish a deterministic target plan | `--catalog-plan`, `--profile-id`, `[--inventory]`, `[--artifacts]`, `[--json]` |
| `status` | list profiles and published plans | `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

Run `python run.py planning status`, `python run.py planning plan`, or
`python run.py planning inspect`. The direct CLI is offline; the interactive
operator asks for evidence mode and requires default-no consent before publication.
See [`commands/README.md`](commands/README.md) for the handler boundary.

Published plans live at
`{artifacts_root}/document_planning/plans/<plan_id>/plan.json`, with target parts
under form partitions. There is no mutable `current` pointer for plans.

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
| Logical Artifact | Resolution Seam |
| :--- | :--- |
| `distribution_root` | Property |
| `ensure_directories(...)` | Method |
| `runtime_root` | Property |
<!-- AUTOGEN:PATHS:END -->

## Deliberate gaps

- No built-in target profile is selected for an operator; profiles are curated inputs.
- No source refresh, inventory projection, or acquisition is performed. Operators
  use `inventory project` separately when coverage is missing, then plan from its
  published snapshot.
- Constructed XBRL package URLs are unverified candidates; availability is not
  probed during offline planning.
