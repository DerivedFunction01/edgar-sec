# `document_storage` Replacement and Retirement Map

## Status and purpose

`edgar_sec.pipelines.document_storage` is frozen while the accession-document flow
is built. The replacement is not a single pipeline: it is two independent pipelines,
`edgar_sec.pipelines.document_inventory` and
`edgar_sec.pipelines.document_acquisition`, and no module under the frozen package is
imported by either. The planned end state is to remove the package after the S11
payload store is implemented, replacement behavior is verified, consumers and old
artifacts are migrated or retired, and a separate decommission gate passes.

This map records the old responsibilities, the replacement owner or deliberate gap,
and which contracts are invariants to reimplement versus historical cases to keep as
tests. The replacement owners are the two pipelines above (`document_inventory` owns
S0–S5; `document_acquisition` owns S6–S10), plus cross-cutting S7 and S12 and
inventory-maintenance S8. `R` means reimplement a contract, **not reuse the old module**; `I`
means inspiration/test evidence only; `N` means do not port the old behavior or
schema; `D` means delete the old module at the approved retirement gate.

## Why the old model is not a migration base

The old work unit is a document locator—accession plus path—with locator-level
fetch/checkpoint identity and potentially many `FilingOccurrence` rows. A response
may describe several SGML siblings, but only the body selected by `selected_index`
is processed. Candidate recovery can fetch an exhibit bundle and emit a recovered
primary across occurrences; a stub may trigger another implicit exhibit pass. The
single normalized-row/payload model therefore grew a partial multi-document layer
without making discovery, target intent, acquisition, and processing independent.
See the current [package contract](../../edgar_sec/pipelines/document_storage/README.md).

The replacement splits those concerns: S3 records every observed index row, S5
stores annual accession/entry facts and source-CIK relations, S6 creates explicit
target intent, S9 acquires an exact direct URL or sequence, and S10 processes the
selected body. The old locator key, synthetic occurrence rows, selected-index
acquisition shape, automatic primary recovery, checkpoint schema, and payload parts
are not carried forward.

## Package-module dispositions

Every linked module below is a retirement candidate (**D**). Replacement ownership
is stated separately; the old source file stays frozen until all consumers and
artifacts have crossed the decommission gate.

| Current module | Current role | Replacement disposition | Existing mirrored evidence |
|---|---|---|---|
| [`__init__.py`](../../edgar_sec/pipelines/document_storage/__init__.py) | Package docstring; no exports. | **N · D** No replacement API. | No dedicated module test; package import is exercised by operator/CLI tests. |
| [`paths.py`](../../edgar_sec/pipelines/document_storage/paths.py) | Published/transient snapshot, fixture, review, and chunk paths. | **N · D** New inventory/acquisition path wrappers use the shared project root and generic transient/pointer helpers; do not retain `DocumentStoragePaths` or add dataset-specific foundation path properties. | [`test_paths.py`](../../tests/pipelines/document_storage/test_paths.py) |
| [`candidates.py`](../../edgar_sec/pipelines/document_storage/candidates.py) | Pre-2005 statutory-exhibit candidate gate using dates, names, and form tokens. | **I · N · D** Preserve edge cases as tests only; do not carry over the candidate window or filename-based selection. | [`test_candidates.py`](../../tests/pipelines/document_storage/test_candidates.py), [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`candidate_recovery.py`](../../edgar_sec/pipelines/document_storage/candidate_recovery.py) | Bundle-first exhibit acquisition that may emit a recovered primary across occurrences. | **I · N · D** The old two-body cases inform tests; S6/S9 select explicit targets and do not infer a primary while fetching an exhibit. | [`test_fetching.py`](../../tests/pipelines/document_storage/test_fetching.py), [`test_resolution.py`](../../tests/pipelines/document_storage/test_resolution.py) |
| [`resolution.py`](../../edgar_sec/pipelines/document_storage/resolution.py) | Resolves a requested locator to a unique basename/form match, including lowest-sequence primary inference. | **I · N · D** Ambiguity cases are useful; do not use its primary inference or sequence ordering as a target rule. | [`test_resolution.py`](../../tests/pipelines/document_storage/test_resolution.py) |
| [`catalog_plan.py`](../../edgar_sec/pipelines/document_storage/catalog_plan.py) | Validates and streams chunked `filing_catalog` locator plans. | **R · N · D** Reimplement pre-fetch validation and deterministic input identity in S1/S6; do not import its locator/chunk schema. | [`test_catalog_plan.py`](../../tests/pipelines/document_storage/test_catalog_plan.py) |
| [`run_manifest.py`](../../edgar_sec/pipelines/document_storage/run_manifest.py) | Pins old catalog-run input digests and validates atomic resume manifests. | **R · N · D** Carry fail-closed identity/reuse as an invariant in stage-specific manifests, not its run schema. | [`test_run_manifest.py`](../../tests/pipelines/document_storage/test_run_manifest.py) |
| [`catalog_execution.py`](../../edgar_sec/pipelines/document_storage/catalog_execution.py) | Replays chunk checkpoints and delegation sidecars for catalog runs. | **I · N · D** Bounded replay is a pattern; old checkpoint and delegation resume semantics are not the S9 fixture protocol. | [`test_catalog_run.py`](../../tests/pipelines/document_storage/test_catalog_run.py) |
| [`work_order.py`](../../edgar_sec/pipelines/document_storage/work_order.py) | Locator chunks, per-locator filing work, and stub-delegation targets. | **I · N · D** Rebuild bounded work orders from S6 targets in S9a; do not retain locator/chunk identity. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`summary.py`](../../edgar_sec/pipelines/document_storage/summary.py) | Plan-derived candidate counts keyed by unique locator. | **N · D** S12 defines stage-specific target/acquisition/processing counts. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`fetching.py`](../../edgar_sec/pipelines/document_storage/fetching.py) | Direct and bundle fetchers; SGML descriptors with one selected body; legacy sequence-one and rendered-path fallback. | **R · I · N · D** Keep request/source/selected-body distinctions and useful route cases; S9b streams to files and S9c selects exact planned sequence. Do not port fallback or whole-body IPC behavior. | [`test_fetching.py`](../../tests/pipelines/document_storage/test_fetching.py), [`test_fixture_operator.py`](../../tests/pipelines/document_storage/test_fixture_operator.py) |
| [`processor.py`](../../edgar_sec/pipelines/document_storage/processor.py) | Form/route processing, binary pass-through, processor identity, and stub evaluation. | **R · N · D** Reuse route and deterministic-fingerprint constraints via the lower-layer engine; S10 does not reuse the class/result shape or automatic stub/refetch behavior. | [`test_processor.py`](../../tests/pipelines/document_storage/test_processor.py) |
| [`processing.py`](../../edgar_sec/pipelines/document_storage/processing.py) | One-locator fetch/process/row assembly over occurrence rows. | **I · N · D** S9/S10 split acquisition and processing and never project one body into synthetic CIK occurrence rows. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`delegation.py`](../../edgar_sec/pipelines/document_storage/delegation.py) | Second-pass exhibit fetch triggered by a stub-primary verdict. | **I · N · D** Keep representative stub inputs for review; the new target plan must declare requests instead of hiding a second fetch. | [`test_delegation.py`](../../tests/pipelines/document_storage/test_delegation.py) |
| [`checkpoint.py`](../../edgar_sec/pipelines/document_storage/checkpoint.py) | Chunk reuse sidecars plus the combined raw/normalized/occurrence snapshot schema. | **N · D** S2/S9 fixtures and S5 immutable snapshots have distinct typed schemas; do not port locator keys, sidecars, or the combined payload row. | [`test_checkpoint.py`](../../tests/pipelines/document_storage/test_checkpoint.py) |
| [`execution.py`](../../edgar_sec/pipelines/document_storage/execution.py) | Resource-derived locator-chunk process pool with checkpoint skipping. | **I · N · D** Retain bounded concurrency, run-identity validation, and validated-checkpoint reuse as patterns; S4 creates new accession-keyed transient Parquet attempts, while S9 owns target worker units. Do not reuse locator chunk identity, schemas, or sidecars. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py), [`test_catalog_run.py`](../../tests/pipelines/document_storage/test_catalog_run.py) |
| [`occurrences.py`](../../edgar_sec/pipelines/document_storage/occurrences.py) | Locator↔occurrence keys, co-filer expansion, and synthetic missing-occurrence rows. | **I · N · D** Avoid duplicated physical fetches, but use S5 accession/source-CIK relations; do not port locator identity or synthetic rows. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`merger.py`](../../edgar_sec/pipelines/document_storage/merger.py) | Per-run publication, pointer-last advancement, occurrence-key merge, and partial-chunk handling. | **R · N · D** Reimplement immutable publication/pointer-last; S5 refuses a failed build rather than dropping bad chunks, and uses accession identity. | [`test_merger.py`](../../tests/pipelines/document_storage/test_merger.py) |
| [`parts.py`](../../edgar_sec/pipelines/document_storage/parts.py) | Quarter-bucketed index/payload parts with path-boundary validation. | **I · N · D** Keep path-containment as a safety invariant; do not carry payload parts, quarter layout, or its part schema. | [`test_parts.py`](../../tests/pipelines/document_storage/test_parts.py) |
| [`queries.py`](../../edgar_sec/pipelines/document_storage/queries.py) | Old snapshot assembly/consolidation SQL keyed by document and occurrence identities. | **I · N · D** Bounded reads are a general constraint; S5 query APIs and annual/CIK indexes have a different logical schema. | [`test_queries.py`](../../tests/pipelines/document_storage/test_queries.py) |
| [`vacuum.py`](../../edgar_sec/pipelines/document_storage/vacuum.py) | Unwired payload consolidation and dependency-aware source purge. | **R · N · D** Retention, parity, and compaction concepts inform S8; do not carry payload identity, quarter consolidation, or source precedence. | [`test_vacuum.py`](../../tests/pipelines/document_storage/test_vacuum.py) |
| [`fixture_store.py`](../../edgar_sec/pipelines/document_storage/fixture_store.py) | SQLite/zstd raw payloads keyed by old locator; a BLOB may hold an entire bundle. | **I · N · D** Retain append-only evidence/read-only replay principles; S2 and S9d have distinct URL/digest schemas and S9d streams file-backed bodies. | [`test_fixture_store.py`](../../tests/pipelines/document_storage/test_fixture_store.py) |
| [`fixture_operator.py`](../../edgar_sec/pipelines/document_storage/fixture_operator.py) | Fills/resumes old locator fixtures from live acquisition. | **I · N · D** Capture/replay is a pattern; S2 and S9d own explicit source-specific capture contracts. | [`test_fixture_operator.py`](../../tests/pipelines/document_storage/test_fixture_operator.py) |
| [`fixture_lineage.py`](../../edgar_sec/pipelines/document_storage/fixture_lineage.py) | Compares old catalog/policy/seed/form lineage, with asymmetric missing-side checks. | **N · D** S2/S9d manifests pin their own schema and source digests; old lineage is not a reuse contract. | [`test_fixture_lineage.py`](../../tests/pipelines/document_storage/test_fixture_lineage.py) |
| [`review_artifacts.py`](../../edgar_sec/pipelines/document_storage/review_artifacts.py) | Fixture-backed normalization reviews, source and normalized files, and the legacy sanitizer. | **I · N · D** Source-first review is useful; S7 rebuilds a preview from a structural HTML parse and allowlist, rather than porting the legacy blacklist sanitizer. S10 owns processing-review output. | [`test_review_artifacts.py`](../../tests/pipelines/document_storage/test_review_artifacts.py) |
| [`review.py`](../../edgar_sec/pipelines/document_storage/review.py) | Diffs old review runs by document ID/text and limited metadata. | **I · N · D** Comparison as a workflow is useful; S7 uses parser-row and target-plan identities instead. | [`test_review.py`](../../tests/pipelines/document_storage/test_review.py) |
| [`operator.py`](../../edgar_sec/pipelines/document_storage/operator.py) | Old pipeline orchestration across chunks, delegation, and publication. | **N · D** New pipeline owners are S4/S5/S9/S10/S12; no old orchestration API is imported. | [`test_operator_and_cli.py`](../../tests/pipelines/document_storage/test_operator_and_cli.py) |
| [`cli.py`](../../edgar_sec/pipelines/document_storage/cli.py) | `documents` run/fill/status/review/fixture command dispatcher. | **N · D** S12 replaces this surface with explicit inventory, query, vacuum, plan, and review commands. | [`test_operator_and_cli.py`](../../tests/pipelines/document_storage/test_operator_and_cli.py) |

The package README and old mirrored tests are removed with the package only after
all listed behaviors have a replacement or an explicit accepted-gap decision.

## Shared lower-layer APIs retained

These modules are **not** part of the retirement set. Reuse is limited to the
listed owner APIs; the new pipeline does not import `pipelines.document_storage`.

| Retained source module | Replacement use and boundary |
|---|---|
| [`domain/identity.py`](../../edgar_sec/domain/identity.py) | Reuse `AccessionNumber` and `Cik`; S5 `filing_cik` derives from the accession prefix, while source-CIK relations remain separate. |
| [`domain/document/route.py`](../../edgar_sec/domain/document/route.py) | Reuse `DocumentRoute`, `document_route()`, and `content_route()` for S10 route selection; do not port the old fetcher’s URL fallback policy. |
| [`domain/sec_urls.py`](../../edgar_sec/domain/sec_urls.py) | Reuse canonicalization/parsing utilities only with S9a HTTPS, allowed-host, and same-accession checks. Do not use full-submission fallback constructors as target selection. |
| [`domain/forms/common/aliases.py`](../../edgar_sec/domain/forms/common/aliases.py) | Reuse `resolve_alias()` per profile form token in S6; do not port old filename/form-token candidate rules. |
| [`domain/filing_catalog/schemas.py`](../../edgar_sec/domain/filing_catalog/schemas.py) | Reuse the published catalog column/schema contract at S1/S6 source adapters only; it is not the target-plan schema. |
| [`engine/forms/normalize.py`](../../edgar_sec/engine/forms/normalize.py) | S10 uses `normalize_document()` and `NormalizationResult` for form-aware text; its planned no-stage-trace mode is required before parallel large-body processing. |
| [`engine/document/unpacking/representation.py`](../../edgar_sec/engine/document/unpacking/representation.py) and [`engine/document/html/cleaner.py`](../../edgar_sec/engine/document/html/cleaner.py) | Reused transitively by the S10 normalizer for decoding/ASCII-PRE and visible HTML/iXBRL processing; they do not extract structured XBRL facts. |
| [`engine/document/unpacking/unpacker.py`](../../edgar_sec/engine/document/unpacking/unpacker.py) | Small-fixture parity oracle only. S9c requires a separate bounded streaming extractor for large bundles. |
| [`foundation/hashing.py`](../../edgar_sec/foundation/hashing.py), [`foundation/serialization.py`](../../edgar_sec/foundation/serialization.py) | Reuse streaming digests and canonical JSON; do not reuse old locator-key composition. |
| [`foundation/regex/builder.py`](../../edgar_sec/foundation/regex/builder.py), [`foundation/text/dates.py`](../../edgar_sec/foundation/text/dates.py) | Retain the shared regex/date helpers; use only where a new contract needs them. Do not carry the old candidate regex or era window. |
| [`foundation/runtime/resources.py`](../../edgar_sec/foundation/runtime/resources.py), [`foundation/runtime/memory.py`](../../edgar_sec/foundation/runtime/memory.py), [`foundation/runtime/paths.py`](../../edgar_sec/foundation/runtime/paths.py) | Reuse resource-derived concurrency, reclamation, and project roots. Old `DOCUMENTS_DATASET`/`DocumentStoragePaths` contracts are not carried forward. |
| [`foundation/runtime/settings/__init__.py`](../../edgar_sec/foundation/runtime/settings/__init__.py) | Reuse the modular settings registry for new byte/resource budgets; do not retain old `documents.*` tuning as a shared phase configuration. |
| [`infra/broker/sec_broker.py`](../../edgar_sec/infra/broker/sec_broker.py), [`infra/sec_http/client.py`](../../edgar_sec/infra/sec_http/client.py) | Reuse the shared broker, SEC session, pacing/cache/retry/failure ledger. S9b needs a streaming-to-stage extension; current byte-returning `fetch()` alone is insufficient. |
| [`infra/storage/atomic.py`](../../edgar_sec/infra/storage/atomic.py), [`infra/storage/duckdb.py`](../../edgar_sec/infra/storage/duckdb.py), [`infra/storage/parquet.py`](../../edgar_sec/infra/storage/parquet.py) | Reuse atomic writes, resource-bounded DuckDB connections/safe SQL, and repository Parquet contracts. Do not reuse payload-part schemas. |
| [`infra/storage/manifests.py`](../../edgar_sec/infra/storage/manifests.py) | Conditional reuse only for generic atomic manifest/pointer helpers if they can represent annual partitions, part digests, inherited refs, lookup ranges, and active-plan retention. Do not carry its payload `doc_ids` model. |

The old pipeline’s `domain/document/acquisition.py`, `domain/document/models.py`,
`engine/document/html/tree.py`, form decision/page-marker/plugin evaluators, and
`foundation/compression.py` are not new acquisition, target, or review APIs. Old
document/acquisition models and occurrence IDs are expressly not reused; the tree
parser is not S7’s inert sanitizer; the old compression codec is not the S2/S9d
fixture contract. Keep only independently owned lower-layer behavior named above.

## Existing consumers to migrate

No production Python module outside the package directly imports
`edgar_sec.pipelines.document_storage`. The absence of imports does **not** mean the
package is unused:

| Current consumer | Existing dependency | Required disposition before package deletion |
|---|---|---|
| [`run.py`](../../run.py) | The public `documents` command dynamically dispatches to `document_storage.cli`. | Repoint/retire the command route and update its CLI documentation. |
| [`apps/viewer/loaders.py`](../../edgar_sec/apps/viewer/loaders.py), [`apps/viewer/server.py`](../../edgar_sec/apps/viewer/server.py) | `load_document_storage`, loader registry, and document APIs read old published/transient layouts. | Migrate to new read-only artifacts or retire the loader/API; migrate/expire old artifact trees. |
| [`foundation/runtime/paths.py`](../../edgar_sec/foundation/runtime/paths.py) | `DOCUMENTS_DATASET` and `ProjectPaths` document-storage path properties are shared path APIs used by the viewer. | Retain project roots; remove/replace old dataset-specific fields only after viewer migration. |
| [`foundation/runtime/settings/catalog.py`](../../edgar_sec/foundation/runtime/settings/catalog.py) | `documents.read_batch_size` and `documents.payload_target_bytes` entries mirror old defaults; the old package uses local defaults, not these values at runtime. | Remove or rename obsolete settings after verifying no configuration consumer remains. |
| [`foundation/scanners/sql_interpolation.py`](../../edgar_sec/foundation/scanners/sql_interpolation.py) | `_SQL_COMPILER_PATHS` contains an exception for `document_storage/fixture_store.py`. | Remove the exception when its SQL module is deleted. |

The old package's direct-import test suite is under
[`tests/pipelines/document_storage/`](../../tests/pipelines/document_storage/).
Replace tests by new stage-owned mirrored tests; do not retain imports merely to
keep the old package test suite runnable. `tests/apps/viewer` also constructs old
snapshot trees and must move with the viewer. Preserve or relocate the form
normalization goldens in `tests/fixtures/document_storage/` while
`tests/engine/forms/test_normalize.py` uses them. Other legacy SGML fixtures should
be copied/sanitized into their new S9/S10 fixture owner only when they exercise a
required behavior. [`tests/support.py`](../../tests/support.py) exposes the old
fixture directory and loader helpers; remove or replace those helpers after all
callers migrate. [`tests/pipelines/metadata_sync/test_discovery.py`](../../tests/pipelines/metadata_sync/test_discovery.py)
uses an old-shaped manifest only as a negative fixture; keep that test self-contained
or change it to an explicit invalid-schema fixture when the old shape is removed.

## Decommission gate and map maintenance

Removal is not authorized by freezing the package or by S12’s offline test alone.
After S11 payload storage is implemented, the separate retirement change must:

1. Verify each old behavior is either covered by S0–S12/S11 replacement tests or
   explicitly accepted as an omitted capability; in particular assess candidate
   recovery, stub delegation, binary retention, and old snapshot compatibility.
2. Migrate or retire `run.py`’s public command, viewer loaders/API, path/settings
   consumers, scanner exceptions, and old artifact readers.
3. Migrate, archive, or explicitly expire existing snapshots, fixtures, and review
   runs; validate rollback and retention before deleting data or code.
4. Remove the package, its mirrored tests, CLI registration, and obsolete package
   settings/paths only after repository-wide import, artifact, and command checks
   show no remaining consumer.
5. Update the [root README](../../README.md),
   [`edgar_sec/README.md`](../../edgar_sec/README.md),
   [`pipelines/README.md`](../../edgar_sec/pipelines/README.md), package README
   layouts, [`inventory_snapshot.md`](inventory_snapshot.md),
   [`roadmap/execution_1.md`](../execution_1.md), shared-owner READMEs listed above,
   and this map so no tracked document points at a deleted source module or artifact
   path.

Until that gate is approved and complete, old files are frozen in the tree and the
module links above remain live evidence. No module or artifact is deleted by S9–S12.
