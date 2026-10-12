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
- The current viewer loader does not register the retired document-storage dataset.
  Existing legacy snapshots remain user data but are not exposed through a migrated
  viewer reader.
- Review-run and fixture evidence establishes that positive numbered SEC child names
  map to accession-prefixed archive leaves. A valid observed prefixed child link, or an
  exact positive numbered catalog `primaryDocument`, can be pinned for direct retrieval;
  `0001` is not inherently a placeholder. Exact primary `0000.txt`/`.htm` names remain
  placeholders: inventory planning requires an advertised bundle URL and observed
  positive sequence, while catalog-only targets remain unresolved. An indexed
  `0001.txt`/`.htm` primary without a usable prefixed child link may use its observed
  sequence and bundle URL.
  Child/index size, full-submission bundle size, and S1-reported catalog size remain
  distinct and do not select retrieval mode. S9 follows pinned S6 mode without
  cross-target bundle grouping or ordinary direct-failure fallback.
- Existing files under artifact roots are user data. Snapshots, fixtures, and review
  runs are not deleted as part of source retirement.

## Module dispositions

Each module listed below was retired (**D**) by this implementation. Replacement
ownership is stated in the section above; the historical source files are no longer
present in the repository.

| Legacy module | Historical role | Replacement disposition |
|---|---|---|
| `__init__.py` | Package docstring; no exports. | **N** No replacement API. |
| `paths.py` | Document-storage snapshot, fixture, review, and chunk paths. | **N** New inventory/acquisition path wrappers use shared project roots. |
| `candidates.py` | Historical date/name candidate gate. | **I·N** Retired; do not use to replace observed accession-prefixed locators. |
| `candidate_recovery.py` | Bundle-first exhibit acquisition with recovered primary. | **I·N** S6/S9 select explicit targets; no inferred primary. |
| `resolution.py` | Resolve locator to unique basename/form match. | **I·N** Ambiguity cases useful; no primary inference reuse. |
| `catalog_plan.py` | Validate and stream chunked filing_catalog locator plans. | **R·N** Reimplement pre-fetch validation in S1/S6; no locator/chunk schema. |
| `run_manifest.py` | Pin old catalog-run input digests. | **R·N** Carry fail-closed identity/reuse in stage-specific manifests. |
| `catalog_execution.py` | Replay chunk checkpoints and delegation sidecars. | **I·N** Bounded replay is a pattern; old semantics not S9 protocol. |
| `work_order.py` | Locator chunks and per-locator filing work. | **I·N** Rebuild from S6 targets; no locator/chunk identity. |
| `summary.py` | Plan-derived candidate counts keyed by locator. | **N** S12 defines stage-specific counts. |
| `fetching.py` | Direct and bundle fetchers with SGML descriptors. | **R·I·N** Keep request/source/selected-body distinctions; ordinary direct-failure bundle fallback is not retained. |
| `processor.py` | Form/route processing with binary pass-through. | **R·N** Retired; retain only separately owned normalization and routing contracts. |
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
- `domain/document/route.py` and the narrow unpacker payload-extraction behavior — retained for current engine callers. The obsolete acquisition/model records have been removed; they are not S9 APIs.
- `engine/document/unpacking/scan_filing_bundle()` — retained as a non-S9 reference/oracle, not a production selector or S9 fallback.
- The exhibit-header probe and external EX-13 evidence may remain independently; the old evaluator package and execution SPI are retired, not S10 runtime owners.
- Fixture data used by those tests and the future review CLI.

## Legacy interfaces

The following legacy interfaces are retired or require migration:

- `SecHttpClient.get_bytes()` and `SecBrokerClient.fetch()` return complete response body in memory.
- `extract_target_sub_document_selection()` was removed after its internal caller and parity tests moved to the payload-only extractor. Preserve whole-SGML normalization behavior. `scan_filing_bundle()` remains a non-S9 reference.
- `FilingProcessor.process()` — retired processor/result coupling to payload persistence.
- `domain.document.acquisition` records: `AcquiredSubmission`, `FetchResult`, `BundleFetchResult`, `DocumentReference`.
- `domain.document.models` records: `DocumentLocator`, `FilingOccurrence`, `RawDocumentBlob`, `NormalizedDocument`, `NormalizationFailure`.
- Plugin evaluator modules, their legacy decision records, and `REFETCH_SUB_DOC` runtime support are removed. S10 findings remain diagnostic and cannot schedule S9 work.

## Historical evidence

The retirement record links to historical artifacts:

- `tests/fixtures/document_storage/exhibit_primary.sgm` — synthetic envelope for legacy tests.
- External EX-13 research evidence and any independently retained bounded header probe;
  the old evaluator package and action SPI are removed.
