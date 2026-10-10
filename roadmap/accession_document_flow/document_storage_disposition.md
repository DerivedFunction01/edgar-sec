# `document_storage` Replacement and Retirement Map

## Status and purpose

`edgar_sec.pipelines.document_storage` is frozen while the accession-document flow
is built. The replacement is split across three artifact-connected pipeline packages:
`edgar_sec.pipelines.document_inventory`, `edgar_sec.pipelines.document_planning`, and
`edgar_sec.pipelines.document_acquisition`. No module under the frozen package is
imported by them. The planned end state is to remove the package after the S11 payload
store is implemented, replacement behavior is verified, consumers and old artifacts
are migrated or retired, and a separate decommission gate passes.

This map records the old responsibilities, the replacement owner or deliberate gap,
and which contracts are invariants to reimplement versus historical cases to keep as
tests. The replacement owners are `document_inventory` (S0–S5), `document_planning`
(S6), and `document_acquisition` (S9–S10), plus cross-cutting S7/S12 and
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
acquisition shape, implicit date/name recovery, checkpoint schema, and payload parts
are not carried forward. Catalog-direct `exact_form_with_lazy_index` is a new,
explicitly profile-authorized S9 policy, not reuse of the legacy candidate finder.

The historical rationale was sparse acquisition, not indiscriminate bundle storage:
ordinary work fetched one primary; only a date- and statutory-name-gated apparent
pre-2005 sequence inversion paid for a full bundle, to recover the form-typed primary
and preserve its misplaced exhibit. The aggregate sketch kept attachments lazy and
the raw bundle absent by default; the execution record also required releasing the
bundle before body processing. A separate 10-K evaluator addressed abbreviated
reports that delegate content to EX-13. Those choices reduced redundant transfer and
live bytes within the locator/aggregate model. S6 now makes demand explicit, while
S9 must retain the bounded-transfer, streamed-body, and exact-selected-body resource
properties without inheriting its heuristics. Historical rationale is in
[`old/design.md`](../old/design.md) and
[`old/execution_1.md`](../old/execution_1.md); their empirical claims are historical
evidence, not new selection rules.

## Lifecycle-to-legacy crosswalk

S6 is implemented in `document_planning`; replacement S9/S10 execution and S11
payload publication remain design-only. S6's default generated profile is
primary-only. Companion acquisition occurs only when a selected profile declares
those targets; the annual/EX-13 sample in the [planning specification](subplans/document_planning/specs.md)
is an example, not the default runtime profile.

| Legacy lifecycle | Replacement owner and necessary responsibility | Retire or replace |
|---|---|---|
| Filing-catalog locator plan and candidate gate | S6 consumes the catalog plan for accession scope and emits one row per declared role/type request, resolved against pinned S5 rows or the allowed catalog-direct primary mode. | Remove date-window, filename-token, and candidate-count routing. S6 observed type/sequence/link evidence, not inferred filename intent, determines targets and retrieval mode. |
| `ArchiveFetcher.fetch()` / `fetch_bundle()` and fixture/live URL fallback | S9 validates pinned target locators, performs bounded direct or exact-sequence acquisition, and records source/selected digests and typed outcomes. S9 fixtures provide explicit zero-network replay. | Replace byte-returning pipeline fetch methods and fixture lookup conventions; no archive-root/rendered fallback or implicit full-submission fallback. |
| Single-body SGML selection, candidate recovery, and sequence-1 primary inference | S6 supplies target intent and, for `bundle_sequence`, the exact observed sequence. S9 extracts that sequence; only the separately authorized catalog-direct lazy-index selector can resolve a replacement slot from fresh observed index rows. | Retire selected-index heuristics, lowest-sequence primary inference, and dual-write. Do not interpret target role/type as proof of the SGML child's type. |
| `FilingProcessor.process(AcquiredSubmission)` and evaluator dispatch | S10 accepts the S9 staged body assigned to the immutable target, applies route/form normalization, and returns a versioned metadata-only result plus a consumption receipt. | Replace the bytes-bearing processor/result and remove text-triggered acquisition. Preserve engine normalization, route semantics, deterministic fingerprints, and explicit binary/paper/XML handling. |
| Locator chunks, sidecars, and `DOCUMENT_SNAPSHOT_SCHEMA` | S9 owns an immutable target work order plus resumable per-run target/attempt/resolution state; S10 results are independently recoverable. | Retire locator/occurrence checkpoint identities, delegation sidecars, and the combined raw/normalized row. |
| `merger.publish_snapshot()` and old quarter-bucketed parts | S11 publishes target/slot/result evidence and separate digest-keyed binary/text payload relations through the acquisition DAG; S8 owns inventory maintenance. | Retire the old merger, row/part schemas, old query layout, and legacy vacuum. Pointer-last publication, integrity validation, retention, and compaction remain necessary under their new owners. |
| Legacy fixtures, review artifacts, viewer, and `documents` command | S7/S9 own their distinct review/fixture contracts; S12 owns the integrated surface; the viewer must read the chosen replacement artifacts or lose the old document API. | Migrate or explicitly retire consumers and persisted trees; legacy compatibility is not implied by new payload publication. |

### One historical accession path

`tests/fixtures/document_storage/exhibit_primary.sgm` is a synthetic envelope for
accession `0000320193-02-000123`: its EX-21 is sequence 1 and the 10-K is sequence
3. Given a catalog EX-21 locator and an actual occurrence `filing_date` in the old
window, the frozen `candidate_for()` accepts its statutory filename; the accession
year alone cannot satisfy that gate. `process_chunk()` diverts it to
`run_candidate_recovery()`, which calls `fetch_bundle()`. The archive backend builds
the full-submission `.txt` URL from the locator accession and archive CIK (or replays
the configured fixture); the ordinary direct-fetch URL/rendered fallback is bypassed
on this candidate path. The resolver checks the requested basename and accepted
10-K type, then selects the lowest-sequence form-matching child, not sequence 1. It
processes both the requested EX-21 and
recovered `a10k.htm` primary, projecting rows for occurrences. Both acquired views
retain the catalog filing form `10-K`, so `FilingProcessor` routes each through the
annual evaluator based on form, not the selected SGML child's `<TYPE>`; either can
therefore produce a legacy EX-13 delegation. The worker writes checkpoint rows, the
operator may run the separate delegation fetch/processing pass, and the merger
publishes old index/payload parts before advancing its pointer. This is a stitched
trace of independently tested current functions, not an end-to-end accession test.
On the ordinary locator path, `processing._process_locator()` optionally sends the
selected source bytes to the fixture `payload_sink`, then stores
`ProcessedDocument.payload` in the snapshot's `raw_payload` column with
`ProcessedDocument.text` as `normalized_text`; for text, that payload is normalized
UTF-8, while binary/pass-through routes preserve their source bytes. Candidate
recovery similarly puts the processor output, not the original bundle, in each
`CandidateOutcome.raw_payload`.
The resolver contract is pinned by
[`test_primary_recovered_from_exhibit_position_one`](../../tests/pipelines/document_storage/test_resolution.py)
while candidate date/name contracts are pinned by
[`test_the_accession_year_is_never_a_substitute`](../../tests/pipelines/document_storage/test_candidates.py)
and [`test_the_verified_inversion_sample_is_a_candidate`](../../tests/pipelines/document_storage/test_candidates.py).
These are separate fixture behaviors, not an integrated test or evidence about that
accession's live SEC filing.

For the replacement, given equivalent S5 observations, S6 would independently
plan the primary from `document_type=10-K` and an optional EX-21 from its observed
type/sequence. An unlinked EX-21 can become a `bundle_sequence` target; S9 selects
sequence 1 for that target and sequence 3 for the primary target, each by its own
target identity. If the chosen profile also declares EX-13, it is a third planned
target; if it does not, S10 cannot create one. S10 processes only acquired target
bodies, returns per-target results, and S11 publishes payload/result/slot links by
digest. The legacy resolver test is not a test of the full replacement path; S9/S10
and the S11 publisher still require their planned fixture-to-publication gate.

## Package-module dispositions

Every linked module below is a retirement candidate (**D**). Replacement ownership
is stated separately; the old source file stays frozen until all consumers and
artifacts have crossed the decommission gate.

| Current module | Current role | Replacement disposition | Existing mirrored evidence |
|---|---|---|---|
| [`__init__.py`](../../edgar_sec/pipelines/document_storage/__init__.py) | Package docstring; no exports. | **N · D** No replacement API. | No dedicated module test; package import is exercised by operator/CLI tests. |
| [`paths.py`](../../edgar_sec/pipelines/document_storage/paths.py) | Document-storage snapshot, fixture, review, and chunk paths, with fixture location delegated to the shared foundation helper. | **N · D** New inventory/acquisition path wrappers use shared project roots and generic path/fixture primitives; do not retain `DocumentStoragePaths` or add dataset-specific foundation path properties. | [`test_paths.py`](../../tests/pipelines/document_storage/test_paths.py) |
| [`candidates.py`](../../edgar_sec/pipelines/document_storage/candidates.py) | Pre-2005 statutory-exhibit candidate gate using dates, names, and form tokens. | **I · N · D** Preserve edge cases as tests only; do not carry over the candidate window or filename-based selection. | [`test_candidates.py`](../../tests/pipelines/document_storage/test_candidates.py), [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`candidate_recovery.py`](../../edgar_sec/pipelines/document_storage/candidate_recovery.py) | Bundle-first exhibit acquisition that may emit a recovered primary across occurrences. | **I · N · D** The old two-body cases inform tests; S6/S9 select explicit targets and do not infer a primary while fetching an exhibit. | [`test_fetching.py`](../../tests/pipelines/document_storage/test_fetching.py), [`test_resolution.py`](../../tests/pipelines/document_storage/test_resolution.py) |
| [`resolution.py`](../../edgar_sec/pipelines/document_storage/resolution.py) | Resolves a requested locator to a unique basename/form match, including lowest-sequence primary inference. | **I · N · D** Ambiguity cases are useful; do not use its primary inference or sequence ordering as a target rule. | [`test_resolution.py`](../../tests/pipelines/document_storage/test_resolution.py) |
| [`catalog_plan.py`](../../edgar_sec/pipelines/document_storage/catalog_plan.py) | Validates and streams chunked `filing_catalog` locator plans. | **R · N · D** Reimplement pre-fetch validation and deterministic input identity in S1/S6; do not import its locator/chunk schema. | [`test_catalog_plan.py`](../../tests/pipelines/document_storage/test_catalog_plan.py) |
| [`run_manifest.py`](../../edgar_sec/pipelines/document_storage/run_manifest.py) | Pins old catalog-run input digests and validates atomic resume manifests. | **R · N · D** Carry fail-closed identity/reuse as an invariant in stage-specific manifests, not its run schema. | [`test_run_manifest.py`](../../tests/pipelines/document_storage/test_run_manifest.py) |
| [`catalog_execution.py`](../../edgar_sec/pipelines/document_storage/catalog_execution.py) | Replays chunk checkpoints and delegation sidecars for catalog runs. | **I · N · D** Bounded replay is a pattern; old checkpoint and delegation resume semantics are not the S9 fixture protocol. | [`test_catalog_run.py`](../../tests/pipelines/document_storage/test_catalog_run.py) |
| [`work_order.py`](../../edgar_sec/pipelines/document_storage/work_order.py) | Locator chunks, per-locator filing work, and stub-delegation targets. | **I · N · D** Rebuild bounded work orders from S6 targets in `acquisition project`; do not retain locator/chunk identity. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`summary.py`](../../edgar_sec/pipelines/document_storage/summary.py) | Plan-derived candidate counts keyed by unique locator. | **N · D** S12 defines stage-specific target/acquisition/processing counts. | [`test_worker.py`](../../tests/pipelines/document_storage/test_worker.py) |
| [`fetching.py`](../../edgar_sec/pipelines/document_storage/fetching.py) | Direct and bundle fetchers; SGML descriptors with one selected body; legacy sequence-one and rendered-path fallback. | **R · I · N · D** Keep request/source/selected-body distinctions and useful route cases; `acquisition run` streams bodies and selects the exact planned sequence. Do not port fallback or whole-body IPC behavior. | [`test_fetching.py`](../../tests/pipelines/document_storage/test_fetching.py), [`test_fixture_operator.py`](../../tests/pipelines/document_storage/test_fixture_operator.py) |
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
| [`fixture_store.py`](../../edgar_sec/pipelines/document_storage/fixture_store.py) | SQLite/zstd raw payloads keyed by old locator; a BLOB may hold an entire bundle. | **I · N · D** Retain append-only evidence/read-only replay principles; S2 and S9 fixture commands have distinct URL/digest schemas. S9 stores exact response bytes as SQLite BLOBs, not as a separate body-file store. | [`test_fixture_store.py`](../../tests/pipelines/document_storage/test_fixture_store.py) |
| [`fixture_operator.py`](../../edgar_sec/pipelines/document_storage/fixture_operator.py) | Fills/resumes old locator fixtures from live acquisition. | **I · N · D** Capture/replay is a pattern; S2 and S9 own explicit source-specific capture contracts. | [`test_fixture_operator.py`](../../tests/pipelines/document_storage/test_fixture_operator.py) |
| [`fixture_lineage.py`](../../edgar_sec/pipelines/document_storage/fixture_lineage.py) | Compares old catalog/policy/seed/form lineage, with asymmetric missing-side checks. | **N · D** S2/S9 manifests pin their own schema and source digests; old lineage is not a reuse contract. | [`test_fixture_lineage.py`](../../tests/pipelines/document_storage/test_fixture_lineage.py) |
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
| [`domain/sec_urls.py`](../../edgar_sec/domain/sec_urls.py) | Reuse canonicalization/parsing utilities only with S9's HTTPS, allowed-host, and same-accession checks. Do not use full-submission fallback constructors as target selection. |
| [`domain/forms/common/aliases.py`](../../edgar_sec/domain/forms/common/aliases.py) | Reuse `resolve_alias()` per profile form token in S6; do not port old filename/form-token candidate rules. |
| [`domain/filing_catalog/schemas.py`](../../edgar_sec/domain/filing_catalog/schemas.py) | Reuse the published catalog column/schema contract and plan-version contract at S1/S6 source adapters only; it is not the S6 target-plan schema. |
| [`engine/forms/normalize.py`](../../edgar_sec/engine/forms/normalize.py) | S10 uses `normalize_document()` and `NormalizationResult` for form-aware text; its planned no-stage-trace mode is required before parallel large-body processing. |
| [`engine/document/unpacking/representation.py`](../../edgar_sec/engine/document/unpacking/representation.py) and [`engine/document/html/cleaner.py`](../../edgar_sec/engine/document/html/cleaner.py) | Reused transitively by the S10 normalizer for decoding/ASCII-PRE and visible HTML/iXBRL processing; they do not extract structured XBRL facts. |
| [`engine/document/unpacking/unpacker.py`](../../edgar_sec/engine/document/unpacking/unpacker.py) | Small-fixture parity oracle only. `acquisition run` requires bounded exact-sequence extraction for large bundles. |
| [`foundation/hashing.py`](../../edgar_sec/foundation/hashing.py), [`foundation/serialization.py`](../../edgar_sec/foundation/serialization.py) | Reuse streaming digests and canonical JSON; do not reuse old locator-key composition. |
| [`foundation/regex/builder.py`](../../edgar_sec/foundation/regex/builder.py), [`foundation/text/dates.py`](../../edgar_sec/foundation/text/dates.py) | Retain the shared regex/date helpers; use only where a new contract needs them. Do not carry the old candidate regex or era window. |
| [`foundation/runtime/resources.py`](../../edgar_sec/foundation/runtime/resources.py), [`foundation/runtime/memory.py`](../../edgar_sec/foundation/runtime/memory.py), [`foundation/runtime/paths.py`](../../edgar_sec/foundation/runtime/paths.py) | Reuse resource-derived concurrency, reclamation, and project roots. Old `DOCUMENTS_DATASET`/`DocumentStoragePaths` contracts are not carried forward. |
| [`foundation/runtime/settings/__init__.py`](../../edgar_sec/foundation/runtime/settings/__init__.py) | Reuse the modular settings registry for new byte/resource budgets; do not retain old `documents.*` tuning as a shared phase configuration. |
| [`infra/broker/sec_broker.py`](../../edgar_sec/infra/broker/sec_broker.py), [`infra/sec_http/client.py`](../../edgar_sec/infra/sec_http/client.py) | Reuse the shared broker, SEC session, pacing/cache/retry/failure ledger. S9's run command needs a streaming-to-stage extension; current byte-returning `fetch()` alone is insufficient. |
| [`infra/storage/atomic.py`](../../edgar_sec/infra/storage/atomic.py), [`infra/storage/duckdb.py`](../../edgar_sec/infra/storage/duckdb.py), [`infra/storage/parquet.py`](../../edgar_sec/infra/storage/parquet.py) | Reuse atomic writes, resource-bounded DuckDB connections/safe SQL, and repository Parquet contracts. Do not reuse payload-part schemas. |
| [`infra/storage/atomic.py`](../../edgar_sec/infra/storage/atomic.py) | Reuse generic atomic JSON/pointer primitives only if they can express the owning pipeline's manifest contract; do not carry a payload `doc_ids` model. |

The old pipeline’s `domain/document/acquisition.py`, `domain/document/models.py`,
`engine/document/html/tree.py`, form decision/page-marker/plugin evaluators, and
`foundation/compression.py` are not new acquisition, target, or review APIs. Old
document/acquisition models and occurrence IDs are expressly not reused; the tree
parser is not S7’s inert sanitizer; the old compression codec is not the S2/S9
fixture contract. Keep only independently owned lower-layer behavior named above.

## Evaluator and delegation disposition

[`FilingProcessor.process()`](../../edgar_sec/pipelines/document_storage/processor.py)
normalizes one selected body, then invokes `get_plugin(locator.form).evaluator(result.text)`
for non-paper, non-binary bodies. For a 10-K,
[`evaluate_annual()`](../../edgar_sec/engine/forms/plugins/evaluators/annual.py)
searches for an EX-13 anchor and nearby delegation verbs; the first qualifying match
returns `REFETCH_SUB_DOC`, `target_exhibit="EX-13"`, and span/line diagnostics.
[`processing._process_locator()`](../../edgar_sec/pipelines/document_storage/processing.py)
persists that request in a delegation sidecar, and
[`operator._publish_delegations()`](../../edgar_sec/pipelines/document_storage/operator.py)
later fetches/resolves/processes the exhibit through
[`delegation.resolve_delegated_exhibit()`](../../edgar_sec/pipelines/document_storage/delegation.py).
This is real legacy
second-pass acquisition, not merely a report annotation. Although
`evaluate_annual()` has a post-2011 shortcut, the only production caller passes no
`filing_year`, so the shortcut cannot fire on this path. The 20-F plugin uses the
generic evaluator; it does not run this EX-13 detector.

S6 makes evaluator-driven scheduling obsolete when a profile declares the
companion: the target exists before acquisition and has independent required or
optional status. It does not make the linguistic signal inherently useless. Retain
the phrases as historical fixture evidence; any future S10 finding is diagnostic
only, cannot repair the plan, and requires the separate evidence/review gate in
`S10_exhibit_assessment.md`. The catalog-direct `exact_form_with_lazy_index` screen
is a distinct S9 policy: only that pinned selector can trigger a bounded index
lookup, and only observed index type evidence can select another physical slot.

The same fate applies to the other evaluator routing surface, but not to form
normalization: `engine/forms/plugins/evaluators/current.py` and
`quarterly.py` always return `PROCEED`; quarterly metadata shortcuts are likewise
unreachable because the caller supplies only text. `evaluate_generic()` in
`engine/forms/plugins/base.py` also only proceeds. Production evaluator/registry use
is confined to the legacy `FilingProcessor`; mirrored tests under
`tests/engine/forms/plugins/` including
[`test_annual.py`](../../tests/engine/forms/plugins/evaluators/test_annual.py) pin
these standalone contracts. After the processor caller migrates, remove the evaluator-only SPI,
`DecisionAction.REFETCH_SUB_DOC`, and plugin registry/evaluator modules only if a
repository-wide caller check confirms no remaining consumer. Keep
`engine/forms/cover/profiles.py`, `engine/forms/normalize.py`, and their form
evidence: they perform current normalization and are not the evaluator router.
Also update the now-stale production-consumer and deliberate-gap prose in
`edgar_sec/engine/forms/plugins/README.md` when that migration happens.

The provisional post-selection primary-versus-exhibit assessment is specified in
[S10_exhibit_assessment.md](subplans/S10_exhibit_assessment.md); its evidence gate
does not pass on the upload sketch alone. The full legacy call path and verified
failure modes are recorded in
[S10_legacy_processing_trace.md](subplans/S10_legacy_processing_trace.md).

## Shared interfaces and conditional retirements

These are migration boundaries, not permission to remove engine/domain APIs when
the old package is deleted:

| Current interface or symbol | Required replacement / retained behavior | Removal precondition |
|---|---|---|
| [`SecHttpClient.get_bytes()`](../../edgar_sec/infra/sec_http/client.py) and [`SecBrokerClient.fetch()`](../../edgar_sec/infra/broker/sec_broker.py) return the complete response body in memory; `ArchiveFetcher.fetch(DocumentLocator)` / `fetch_bundle()` build `FetchResult` / `BundleFetchResult` with payload bytes. | Add the S9 streaming-to-managed-stage transport and body-free broker/process handoff. Retain shared SEC pacing, retries, cache policy where compatible, and failure ledger. | Remove the legacy fetch protocols/backends only after S9 direct/bundle acquisition, failure outcomes, fixture replay, and consumers pass without byte-returning legacy APIs. |
| `extract_target_sub_document_selection(raw_bytes, ...)` and `scan_filing_bundle(...)` in [`engine/document/unpacking/unpacker.py`](../../edgar_sec/engine/document/unpacking/unpacker.py). | S9 needs the planned bounded [`extract_bundle_sequence(source: StagedBodyRef, selector: BundleSelector, ...)`](subplans/S9c_sgml_extraction.md#interface) interface, returning selected-body metadata/digests and a staged child body. The existing bytes-based API remains useful to `representation.py`, small-fixture parity tests, and normalizer envelope defense-in-depth. | Do not remove general unpack/representation helpers merely because the old fetcher goes away. Replace only legacy fallback/resolution helpers after all engine and test callers move to the bounded API. |
| `FilingProcessor.process(AcquiredSubmission) -> ProcessedDocument`; `ProcessedDocument.payload` and `DocumentProcessor` couple transformation to legacy payload persistence. `processing._process_locator()` and `review_artifacts` call the current normalizer on bytes. | Implement the planned S10 `process_target(request: ProcessingRequest, ...) -> ProcessingResult` over a verified `StagedBodyRef`; return metadata/digests/status rather than payload bytes and write the S9 `BodyConsumptionReceipt` only after body consumption. Add `capture_stage_trace=False` to `normalize_document(raw_bytes, ...)` while preserving current default behavior and golden output; retain existing callers' default and mirrored coverage in [`test_normalize.py`](../../tests/engine/forms/test_normalize.py). | Retire the processor/result/protocol only after S10 route/fingerprint/failure tests and S9 receipt integration pass, all callers including review migrate, and no legacy payload writer consumes the result. The normalizer itself remains engine functionality. |
| `domain.document.acquisition`: legacy `AcquiredSubmission`, `FetchResult`, `BundleFetchResult`, `DocumentReference`, resolution outcomes, and `SubmissionDocument`. | Most records describe the old pipeline, but `engine/document/unpacking/unpacker.py` still imports `SubmissionDocument` and `describe_submission_document` to report observed SGML headers. Move/replace that descriptor contract before removing the module; keep S9 acquisition models under its pipeline owner. | Split the active header descriptor from old byte-bearing acquisition/resolution types, then verify `unpacker.py` and all mirrored tests no longer import the retired module. |
| `domain.document.models.DocumentLocator`, `FilingOccurrence`, `RawDocumentBlob`, `NormalizedDocument`, and `NormalizationFailure`; legacy candidate/resolution helpers in `document_storage.candidates`, `resolution`, `occurrences`, and `candidate_recovery`. | Accession identity and S5 source-CIK relations remain. S6 target rows and S9 physical slots replace locator/occurrence identity for acquisition; do not synthesize co-filer occurrences. | Audit each model/helper's external importers and tests before removal. Remove candidate-date/name routing only after S6 plans own target selection and no legacy execution/review path calls `candidate_for()` or `resolve_candidate_filing()`. |
| `FilingProcessor` calls `get_plugin()`; plugin evaluator modules and `DecisionAction` / `EvaluatorDecision` represent triage and re-fetch. | No evaluator schedules acquisition in S6/S9/S10. Preserve cover profiles/normalization; retain EX-13 language only as evidence or reviewed advisory output. | Remove after all processor, CLI, review, domain-model, and tests migrate; confirm plugin stage flags/evaluator symbols have no other production users. |

The SGML selection helpers are not interchangeable: legacy
`extract_from_sgml_envelope()` derives accepted types from the requested form and
allows filename/sequence-1/first-plausible fallback, while the legacy inversion
resolver uses strict requested-basename and accepted-type checks plus lowest
accepted sequence. Replacement S9 must use the pinned sequence and report absent,
duplicate, malformed, or oversize cases distinctly; it must not port either policy.

## Existing consumers to migrate

No production Python module outside the package directly imports
`edgar_sec.pipelines.document_storage`. The absence of imports does **not** mean the
package is unused:

| Current consumer | Existing dependency | Required disposition before package deletion |
|---|---|---|
| [`run.py`](../../run.py) | The public `documents` command dynamically dispatches to `document_storage.cli`. | Repoint/retire the command route and update its CLI documentation. |
| [`apps/viewer/loaders.py`](../../edgar_sec/apps/viewer/loaders.py), [`apps/viewer/server.py`](../../edgar_sec/apps/viewer/server.py) | `load_document_storage`, loader registry, and document APIs read old published/transient layouts. | Migrate to new read-only artifacts or retire the loader/API; migrate/expire old artifact trees. |
| [`foundation/runtime/paths.py`](../../edgar_sec/foundation/runtime/paths.py), [`foundation/runtime/fixtures.py`](../../edgar_sec/foundation/runtime/fixtures.py) | Project roots and generic dataset-scoped fixture locations/envelope validation; no document-storage-specific `ProjectPaths` properties. | Retain project roots and reusable fixture mechanics; keep storage paths and payload details in the owning pipeline until its decommission. |
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
The ordered retirement work starts only after these replacement gates pass:

1. Implement bounded S9 transport and exact-sequence extraction, S10's staged-body
   processing/result/receipt contract, and S11's approved durable publisher. Pass the
   fixture-driven S9-to-S10 gate and read-back/publication integrity checks; a test
   that stops at a selected body is not end-to-end parity.
2. Exercise a representative pinned catalog/S5-to-S6-to-S9-to-S10-to-S11 path,
   including direct and bundle targets, optional missing targets, inversion fixture,
   EX-13 declared and undeclared cases, binary retention, retry/resume, and processing
   failures. Record accepted omissions (including evaluator diagnostics) explicitly.
3. Migrate or retire `run.py`'s public command, viewer loaders/API, old artifact
   readers, foundation settings consumers, and scanner exceptions. Prove new query
   consumers can read the published replacement artifacts.
4. Decide old snapshot, fixture, review-run, and viewer-data retention/migration;
   verify backup/rollback and expiration behavior before deleting persisted data.
5. Remove `document_storage` and its mirrored tests only after repository-wide import,
   artifact-path, fixture-helper, command, and test checks show no remaining consumer.
   Then remove conditional domain/plugin symbols and stale settings only after their
   individual caller preconditions in the cross-layer table pass.
6. Update the [root README](../../README.md),
   [`edgar_sec/README.md`](../../edgar_sec/README.md),
   [`pipelines/README.md`](../../edgar_sec/pipelines/README.md), package README
   layouts, [`inventory_snapshot.md`](inventory_snapshot.md),
   [`roadmap/old/execution_1.md`](../old/execution_1.md),
   [`engine/forms/plugins/README.md`](../../edgar_sec/engine/forms/plugins/README.md),
   shared-owner READMEs, and this map so no tracked document points at a deleted
   source module or artifact path.

Until that gate is approved and complete, old files are frozen in the tree and the
module links above remain live evidence. No module or artifact is deleted by S9–S12.
