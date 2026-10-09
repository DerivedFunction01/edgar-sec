# S6 Document Planning Implementation Plan

This plan sequences S6 implementation and defines file ownership so independent
work can proceed after the shared contracts below are frozen. The normative
profile, matching, artifact, and operator contract is in [specs.md](specs.md).
This is the main S6 implementation plan, not a follow-up correction; accepted
behavior belongs in the main S6 specification before implementation begins.

## 1. Shared decisions to freeze first

Before parallel implementation, agree on these interfaces and invariants:

- Every plan requires a published filing-catalog plan. It defines the accession
  scope; S6 adds no form, date, cohort, seed, or limit filters.
- An inventory snapshot is optional evidence. With one, every target resolves
  against its pinned index only. An accession missing from it emits
  `unresolved` with `accession_not_indexed`, regardless of `optional`; there is
  no row-level fallback to the catalog path.
- Without a snapshot, only a primary-only profile is valid. Those rows use
  `catalog_direct` and `catalog_metadata` evidence.
- Catalog occurrences are aggregated by canonical accession before profile
  matching. Conflicting form or filing-date facts refuse the plan. If a snapshot
  is supplied, a conflict with its accession form or filing date also refuses.
- `source_origin` describes the locator resolver, not the plan's scope: it is
  `catalog_direct` only for catalog-only plans and `inventory_index` whenever
  a snapshot was selected, including unindexed-accession outcomes. An unindexed
  accession has `availability_evidence="none"`.
- The manifest and `plan_id` pin the catalog plan ID and digest, optional
  snapshot ID and digest (explicit nulls when absent), profile digest, target
  schema version, and matcher version. Remove the single-source
  `source_kind/source_id/source_digest` model.
- Output rows retain `form` and `filing_date`; target files are partitioned by
  form using `filing_catalog.paths.form_partition_name` and reject any selected
  form-name collision. The actual filing-catalog plan layout is
  `targets/form=<escaped-form>/data.parquet`; S6 uses its own
  `targets/form=<escaped-form>/part-NNNNN.parquet` shards. Part ordering and
  row-group boundaries are fixed in `specs.md`.
- S9 reads only the resulting plan. Content-addressed response storage is not
  a promise that S9 can skip a fetch for a new target: response hashes are not
  known until bytes have been acquired.

## 2. Intended package and artifact paths

The S6 package is a new Layer 4 pipeline. Every module has a mirrored test;
each test directory is a package.

| Path | Responsibility | Mirrored test |
|---|---|---|
| `edgar_sec/pipelines/document_planning/paths.py` | Resolve profile and artifact roots, validate identifiers, define partition and plan paths. | `tests/pipelines/document_planning/test_paths.py` |
| `edgar_sec/pipelines/document_planning/__init__.py` | Package docstring/version only; no child re-exports. | `tests/pipelines/document_planning/__init__.py` |
| `edgar_sec/pipelines/document_planning/schemas.py` | Own target Arrow schema and schema/version constants. | `tests/pipelines/document_planning/test_schemas.py` |
| `edgar_sec/pipelines/document_planning/profiles.py` | Discover, validate, normalize, and digest profiles; enforce catalog-only profile restriction. | `tests/pipelines/document_planning/test_profiles.py` |
| `edgar_sec/pipelines/document_planning/catalog_scope.py` | Validate catalog plan bundle, stream selected target rows, aggregate accessions, and verify catalog facts. | `tests/pipelines/document_planning/test_catalog_scope.py` |
| `edgar_sec/pipelines/document_planning/inventory_evidence.py` | Pin and stream the named S5 snapshot; semi-join catalog accessions and check metadata consistency. | `tests/pipelines/document_planning/test_inventory_evidence.py` |
| `edgar_sec/pipelines/document_planning/planner.py` | Apply profile rules to the normalized catalog scope and optional evidence; emit bounded target rows. | `tests/pipelines/document_planning/test_planner.py` |
| `edgar_sec/pipelines/document_planning/publication.py` | Compute plan identity/digest, stage and validate Parquet parts, atomically publish and reuse bundles. | `tests/pipelines/document_planning/test_publication.py` |
| `edgar_sec/pipelines/document_planning/discovery.py` | Discover and validate published plan envelopes without scanning source artifacts. | `tests/pipelines/document_planning/test_discovery.py` |
| `edgar_sec/pipelines/document_planning/commands/plan.py` | Validate command inputs, perform preflight, call planner/publication, report coverage and counts. | `tests/pipelines/document_planning/commands/test_plan.py` |
| `edgar_sec/pipelines/document_planning/commands/inspect.py` | Validate and report one plan's pins, counts, and parts. | `tests/pipelines/document_planning/commands/test_inspect.py` |
| `edgar_sec/pipelines/document_planning/commands/status.py` | List profiles and plans without reading source rows. | `tests/pipelines/document_planning/commands/test_status.py` |
| `edgar_sec/pipelines/document_planning/commands/README.md` | Command package responsibility and deliberate gaps. | Documentation review |
| `edgar_sec/pipelines/document_planning/commands/__init__.py` | Package docstring only. | `tests/pipelines/document_planning/commands/__init__.py` |
| `edgar_sec/pipelines/document_planning/cli.py` | Define `planning plan`, `inspect`, and `status` CLI commands. | `tests/pipelines/document_planning/test_cli.py` |
| `edgar_sec/pipelines/document_planning/operator.py` | Own the stage-local planning menu and session context. | `tests/pipelines/document_planning/test_operator.py` |
| `edgar_sec/pipelines/document_planning/README.md` | Package contract, public surface, command surface, mirrored tests, and deliberate gaps. | Documentation review |
| `run.py` | Register the independent `planning` launcher entry. | `tests/test_run.py` |
| `README.md`, `edgar_sec/README.md`, `edgar_sec/pipelines/README.md` | Add the new pipeline to the corresponding layout tables. | Documentation review |
| `roadmap/accession_document_flow/implementation.md` and S6 subplans | Keep lifecycle, CLI, acceptance, and module contracts aligned. | Documentation review |

All directories containing Python modules are packages with `__init__.py` files;
initializers do not re-export child symbols. Profiles live under
`policies/document_targets/*.json`. Published plans live
under `{artifacts_root}/document_planning/plans/{plan_id}/`, with `plan.json`
and form-partitioned target parts. The manifest is the sole ordered inventory of
parts; readers do not infer completeness from directory contents.

The launcher registers the package in `run.py` as `planning`. Do not add S6
actions to the Inventory menu. The later `documents plan` alias belongs to S12.

## 3. Dependency graph and parallel work tracks

The contract-freeze task is serial. Once the shared source descriptor, target
schema, manifest fields, and planner interface are agreed, these tracks may run
in parallel:

```text
                         ┌─ Catalog scope adapter ─┐
Contract freeze ─────────┼─ Inventory evidence adapter ─┼─ Planner/publication integration
                         ├─ Profile loader ─────────┘             │
                         ├─ CLI/operator shell ────────────────────┤
                         └─ S9a consumer-contract update ─────────┘
```

| Track | Owns | Depends on | Join condition |
|---|---|---|---|
| A. Contract and profile | `schemas.py`, `profiles.py`, `paths.py`, schema/profile tests, contract changes in `specs.md`. | None; executes first. | Stable `ResolvedProfile`, source-pin, target-row, and manifest contracts. |
| B. Catalog scope | `catalog_scope.py` and mirrored tests. | A's accession/scope DTO and error contract. | Emits a bounded, sorted accession stream with unique accessions and validated shared facts. |
| C. Inventory evidence | `inventory_evidence.py` and mirrored tests. | A's source pin and B's accession stream contract; S5 schema exposure. | Reads one named snapshot only, validates form/date consistency, and yields indexed or unindexed evidence without mutating S5. |
| D. Planning and publication | `planner.py`, `publication.py`, their tests, and final plan-bundle integration tests. | A, B, and C interfaces. | Stable plan identity, bounded target output, per-status/origin/coverage reconciliation, and atomic reuse/refusal behavior. |
| E. CLI/operator | `commands/`, `cli.py`, `operator.py`, launcher registration, CLI/operator tests. | A's public planner API and summary schema; can build menu and picker tests against fakes before D lands. | One-action-per-menu-return, safe cancellation, explicit source choices, clear coverage display, no auto-run/auto-publish. |
| F. Consumer/document integration | S9a source-pin checks, S12 command synopsis, implementation/design/exit-gate references. | A's manifest and row schema. | S9 opens plan Y only; no downstream code or prose relies on the legacy single-source manifest. |

Do not assign multiple tracks ownership of `specs.md`, `schemas.py`, `plan.json`,
or target status semantics at the same time. Track A lands those contracts first;
parallel branches then consume them. Integration changes the shared worktree only
after each track's mirrored tests pass.

## 4. Milestones and verification

1. **Contract freeze:** reconcile S6, detailed specs, S9a, S12, and the root
   roadmap. Verify the old single-source and hybrid-fallback wording is removed.
2. **Source adapters:** test catalog duplicate aggregation and conflict refusal;
   test snapshot pinning, pointer movement immunity, missing-accession handling,
   form/date disagreement refusal, and zero source mutation/network.
3. **Planner/publication:** test catalog-only primary restriction, hybrid
   index-only resolution, stable identity, deterministic form partitions,
   row/status/coverage counts, missing and corrupt source behavior, atomic
   publication, identical reuse, and divergent reuse refusal.
4. **Operator/CLI:** test paginated catalog/profile/snapshot discovery, explicit
   “no inventory evidence” choice, `current` resolution displayed and pinned
   once, unindexed coverage summary, cancellation/no-op, invalid bundle
   reporting, and no automatic transition to inventory execution or S9.
5. **Consumer acceptance:** test S9a against a plan manifest with both source
   pins and confirm it never opens the source plan or snapshot. Verify
   `inventory_index` and `catalog_direct` preserve identical acquisition work
   shapes where both are matched.

Run the targeted mirrored S6 and S9a tests first, then `.venv/bin/python check.py`
for the repository's changed-file gate. Do not use `check.py --all`
unless explicitly requested. Documentation-only changes use `check.py --fast`
and `git diff --check`.

## 5. Deliberate non-goals

- S6 never projects or fetches a missing accession; the operator points to
  `inventory project` instead.
- No per-row catalog fallback occurs in a hybrid plan.
- S9 does not skip a live fetch merely because a prior response body is
  content-addressed; cross-plan acquisition reuse requires a separately designed
  lookup identity.
- S6 does not own catalog filters, inventory mutations, network consent, or the
  integrated cross-stage wizard.
