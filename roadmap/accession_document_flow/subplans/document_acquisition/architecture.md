# S9 acquisition architecture

## Purpose and status

This document fixes the cross-command boundaries for the partial S9 implementation.
The code now includes the S6 v2 target-plan producer, bounded S9 work-order projection,
offline run projection/state, compressed SQLite fixture storage, file-backed HTTP and
broker streaming, and bounded exact-sequence extraction. The S9 runner/lazy-index
integration, S10 processing, and S11 publication remain separate and are not yet
implemented. The integrated sequence is specified in
[the lifecycle plan](lifecycle.md); command-level UX flows belong to the linked
command documents.

## Ownership and layer boundaries

- S9 consumes a published S6 target-plan bundle. It validates the pinned manifest
  and every declared target part, then reads only those local parts. It never opens
  the catalog plan or inventory snapshot again.
- A `catalog_direct` target is a catalog-supplied sequence-1 locator, not
  index-verified document-type evidence. S9 may fetch `-index.html` only when the
  S6-pinned `exact_form_with_lazy_index` policy's body screen raises the specified
  mismatch/unverifiable suspicion. That bounded exception does not read or mutate a
  published S5 snapshot, and it does not rewrite the immutable S6 target plan. A
  caller needing index evidence without catalog-direct recovery publishes it through
  S5 and creates an index-backed S6 plan.
- S9 acquires exact source bytes and, for a bundle target, selects the exact pinned
  sequence. It does not normalize, infer a primary, or publish a durable payload
  snapshot.
- S6 `target_role` and `target_type` remain request intent, not source assertions or
  archive routes. For a primary target the expected statutory type is the pinned
  filing form; the SEC index's primary designation, sequence, and observed body type
  are separate evidence. S9 preserves the selector and target-to-physical-slot
  resolution; S10 joins the acquired body by `target_id` and uses the role to select
  normalization context. The effective body path selects its byte route. Do not add
  `raw: bool`.
- The pipeline may depend downward on `domain`, `engine`, `infra`, and `foundation`.
  It does not import `pipelines.document_storage` or make an upper layer own S9 state.
- The only S6 contract imports are direct, unaliased imports from
  `document_planning.paths` and `document_planning.schemas`. S9 validates the pinned
  bundle itself; it does not import the S6 planner, discovery, or matching services.
- Large-body streaming belongs in the shared SEC HTTP/broker path, and bounded SGML
  parsing belongs in `engine.document.unpacking`. S9 validates targets, owns run
  state, and composes those lower-layer APIs.
- The lazy index path uses the shared SEC broker and a lower-layer parser API; it must
  not import the sibling `document_inventory` pipeline or its S3 services. If the
  current parser is pipeline-owned, extract the parsing contract to an allowed lower
  layer before enabling this path.
- The existing `SecHttpClient.get_bytes()` materializes the response. The additive
  `stream_to_file()` client and broker paths provide bounded transfer; S9 must not wrap
  the byte-returning method and call it streaming. The existing bytes-based
  `unpack_sgml_submission()` remains a small-fixture parity oracle, not the large
  envelope implementation.
- The existing SEC response cache is byte-returning. Until a file-backed cache path
  exists, large-body acquisition must bypass it rather than materialize a cache hit
  through `get_bytes()` and violate the streaming bound.
- The stream API must validate every redirect against the same accession archive
  boundary before accepting the redirected response. S9 uses the shared
  `domain.sec_urls` parser plus an accession-scoped policy; HTTP transport receives
  a validator/callback instead of importing pipeline code.

## Planned module ownership

The package should remain split by contract rather than by command spelling alone:

| Module | Owner contract |
|---|---|
| `paths.py` | Resolve run, staging, distribution, fixture, and snapshot roots; validate IDs and containment. |
| `schemas.py` | Lightweight versioned JSON/handoff contracts shared with S10 and snapshot publication. |
| `arrow_schemas.py` | Versioned Parquet work-order schema; snapshot relation schemas remain gated and absent. |
| `models.py` | Immutable in-memory target, outcome, attempt, and staged-body records. |
| `target_plan.py` | Validate the S6 v2 bundle and stream the immutable S9 work order without reopening upstream inputs. |
| `run_state/` | Create and validate per-run SQLite state, append attempts, apply outcomes, and summarize status. |
| `project.py` | Derive a deterministic transient run from the pinned S6 plan without network access. |
| `runner.py` | Lock a run, schedule bounded target work, and preserve completed results. |
| `distribution_adapter.py` | Adapt acquisition work and outputs to shared distribution infrastructure. |
| `snapshot/` | **Gated** acquisition-owned binary/text Parquet relations and publication over the shared DAG kernel; no S11 adapter exists yet. |
| `fixture_store/` | Store uniformly Zstandard-compressed response evidence in SQLite and replay incrementally; capture orchestration remains TODO. |
| `processing.py` | S10 per-target processing and versioned result publication to transient staging. |
| `cli.py` and `operator.py` | Registered project/status/run/process/publish/fixture/review/snapshot command tracks; project is wired, pending tracks fail closed. |

No `__init__.py` barrel exports. Module names are a design proposal; implementation
may consolidate small command adapters, but it must retain these ownership boundaries
and keep modules below the repository's file-length limit.

## Contract dependencies

The shared schema, paths, and settings proposals are specified in:

- [S9 schemas](schemas.md)
- [S9 paths](paths.md)
- [S9 settings](settings.md)
- [Run-state persistence](run/state.md)
- [Fixture persistence](fixtures/storage.md)

Project, status, run, distribution, fixtures, publication, and operator behavior are
specified in their command documents and the [lifecycle plan](lifecycle.md). These
contracts must consume the shared types above rather than redeclare their own versions.

## Cross-command identity and state

- A run pins `target_plan_id`, `target_plan_digest`, the S6 target schema version,
  and the S9 work-order schema/contract version. Its ID is deterministic from that
  immutable identity; mutable attempt settings do not rewrite the run manifest.
- A `target_id` is scoped by its target-plan ID. The run retains every S6 target row;
  executability and skip reason are explicit, so a skipped target cannot disappear
  from status or be scheduled by a worker.
- An acquisition attempt is append-only evidence. Current target outcome is a
  replaceable projection over attempts, not a rewrite of attempt history.
- Physical acquisition identity is `(accession, sequence)`, not target ID. The
  catalog-direct primary link anchors sequence 1 even when that slot's observed type
  is an exhibit. A target assignment links its request to the selected physical slot;
  retaining sequence-1 bytes does not make them the S10 input when recovery selects a
  different sequence.
- `acquired`, `not_filed`, `required_missing`, `ambiguous`, and `failed` are target
  outcomes. Run cancellation/interruption and active locks are run-level state, not
  target outcomes. Retryability comes from typed error classification, not a CLI label.
- A selected body is a managed file reference carrying its digest and byte size,
  never payload bytes in JSON, SQL rows, Parquet metadata, or process IPC. A matching
  S10 receipt proves consumption but does not authorize cleanup before snapshot
  publication adopts the payload or the run is explicitly discarded.

## Resource and network policy

- Reuse SEC user agent, rate limit, retry, timeout, cache, and failure-ledger policy
  from the SEC settings and broker. Add only acquisition-specific settings where
  existing shared settings do not express a required bound.
- Stream to owner-generated paths and enforce the response-byte ceiling on bytes
  actually received after content decoding. `Content-Length` is only an early
  rejection hint. Oversize and partial responses never become acquired outcomes.
- Derive worker and memory budgets from `derive_resources()` and
  `auto_worker_count()`; keep both submitted work and in-flight bodies bounded.
- Each host's shared broker owns local pacing and failure accounting under that
  machine's configured SEC settings/environment. This is not a cross-host aggregate
  rate limit.

## Rate-limit scope

Workers on one host share that host's configured SEC rate limit. Separate hosts use
their own settings/environment and independent limiters. Cross-host rate coordination
and cross-host rate checks are explicitly out of scope; no cluster-wide rate guarantee
is implied. Acquisition distribution itself remains unimplemented and in planning.
