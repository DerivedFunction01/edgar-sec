# `document_storage` Retirement Record

## Status

`edgar_sec.pipelines.document_storage` has been retired. The package and its
mirrored test suite have been removed from the repository.

This document records the retired pipeline's historical responsibilities and the
replacement owners in the accession-document flow (S0–S12). It is a reference
for understanding legacy behavior and for reviewing accepted gaps; it is not a
specification for new work.

## Replacement owners

The replacement pipeline packages are:

- `edgar_sec.pipelines.document_inventory` — S0–S5
- `edgar_sec.pipelines.document_planning` — S6
- `edgar_sec.pipelines.document_acquisition` — S9–S10

No module under the retired `document_storage` package is imported by them.

## Accepted gaps

The following gaps are accepted as part of the retirement:

- The `documents` CLI and legacy run, fixture-fill, snapshot, consolidation, and
  review commands are retired.
- S9 acquisition remains usable, but its `process`, `publish`, and review commands
  are not replacement processing surfaces. There is no end-to-end normalize/publish
  path until S10/S11 work is implemented.
- `apps.viewer.loaders` currently imports `document_storage` manifest/path modules
  and its document-storage dataset will fail. The discovery mechanism is removed.
- Existing files under artifact roots are user data. Snapshots, fixtures, and review
  runs are not deleted as part of source retirement.

## Module dispositions

Each module listed below was retired (**D**). Replacement ownership is stated in the
section above; the historical source file was removed when the decommission gate
passed.

| Legacy module | Historical role | Replacement disposition |
|---|---|---|
| `__init__.py` | Package docstring; no exports. | **N** No replacement API. |
| `paths.py` | Document-storage snapshot, fixture, review, and chunk paths. | **N** New inventory/acquisition path wrappers use shared project roots. |
| `candidates.py` | Pre-2005 statutory-exhibit candidate gate. | **I·N** Preserve edge cases as tests only. |
| `candidate_recovery.py` | Bundle-first exhibit acquisition with recovered primary. | **I·N** S6/S9 select explicit targets; no inferred primary. |
| `resolution.py` | Resolve locator to unique basename/form match. | **I·N** Ambiguity cases useful; no primary inference reuse. |
| `catalog_plan.py` | Validate and stream chunked filing_catalog locator plans. | **R·N** Reimplement pre-fetch validation in S1/S6; no locator/chunk schema. |
| `run_manifest.py` | Pin old catalog-run input digests. | **R·N** Carry fail-closed identity/reuse in stage-specific manifests. |
| `catalog_execution.py` | Replay chunk checkpoints and delegation sidecars. | **I·N** Bounded replay is a pattern; old semantics not S9 protocol. |
| `work_order.py` | Locator chunks and per-locator filing work. | **I·N** Rebuild from S6 targets; no locator/chunk identity. |
| `summary.py` | Plan-derived candidate counts keyed by locator. | **N** S12 defines stage-specific counts. |
| `fetching.py` | Direct and bundle fetchers with SGML descriptors. | **R·I·N** Keep request/source/selected-body distinctions. |
| `processor.py` | Form/route processing with binary pass-through. | **R·N** Reuse route and deterministic-fingerprint constraints. |
| `processing.py` | One-locator fetch/process/row assembly. | **I·N** S9/S10 split acquisition and processing. |
| `delegation.py` | Second-pass exhibit fetch for stub-primary. | **I·N** Keep representative stub inputs for review. |
| `checkpoint.py` | Chunk reuse sidecars and combined snapshot schema. | **N** S2/S9 fixtures and S5 snapshots have distinct schemas. |
| `execution.py` | Resource-derived locator-chunk process pool. | **I·N** Retain bounded concurrency patterns; no locator identity. |
| `occurrences.py` | Locator↔occurrence keys and synthetic rows. | **I·N** Use S5 accession/source-CIK relations. |
| `merger.py` | Per-run publication and pointer-last advancement. | **R·N** Reimplement immutable publication/pointer-last. |
| `parts.py` | Quarter-bucketed index/payload parts. | **I·N** Keep path-containment invariant. |
| `queries.py` | Old snapshot assembly SQL. | **I·N** S5 query APIs have different logical schema. |
| `vacuum.py` | Payload consolidation and source purge. | **R·N** S8 owns inventory maintenance. |
| `fixture_store.py` | SQLite/zstd raw payloads keyed by old locator. | **I·N** Retain append-only evidence principles; S9 uses different schema. |
| `fixture_operator.py` | Fill/resume old locator fixtures. | **I·N** S2/S9 own explicit source-specific capture contracts. |
| `fixture_lineage.py` | Compare old catalog/policy/seed/form lineage. | **N** S2/S9 manifests pin their own schema. |
| `review_artifacts.py` | Fixture-backed normalization reviews. | **I·N** Source-first review useful; S7 rebuilds preview from parse. |
| `review.py` | Diff old review runs by document ID/text. | **I·N** S7 uses parser-row and target-plan identities. |
| `operator.py` | Old pipeline orchestration. | **N** New pipeline owners are S4/S5/S9/S10/S12. |
| `cli.py` | `documents` run/fill/status/review/fixture commands. | **N** S12 replaces with explicit inventory, query, vacuum, plan, and review. |

## Shared lower-layer APIs retained

These modules are **not** part of the retirement set and remain available:

- `engine/forms/normalize.py` — normalization owner; its behavior and golden tests unchanged.
- `domain/document/route.py`, `domain/document/acquisition.py` — retained while engine unpacking imports them.
- Decision-tree/evaluator implementations and their engine/domain tests — S10 wiring will compose them.
- Fixture data used by those tests and the future review CLI.

## Legacy interfaces

The following legacy interfaces are retired or require migration:

- `SecHttpClient.get_bytes()` and `SecBrokerClient.fetch()` return complete response body in memory.
- `extract_target_sub_document_selection()` and `scan_filing_bundle()` in `engine/document/unpacking/unpacker.py`.
- `FilingProcessor.process()` — legacy processor/result coupling to payload persistence.
- `domain.document.acquisition` records: `AcquiredSubmission`, `FetchResult`, `BundleFetchResult`, `DocumentReference`.
- `domain.document.models` records: `DocumentLocator`, `FilingOccurrence`, `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`.
- Plugin evaluator modules and `DecisionAction.REFETCH_SUB_DOC` — no evaluator schedules acquisition in S6/S9/S10.

## Historical evidence

The retirement record links to historical artifacts:

- `tests/fixtures/document_storage/exhibit_primary.sgm` — synthetic envelope for legacy tests.
- Legacy decision-tree and evaluator code retained in `engine/forms/plugins/`.
