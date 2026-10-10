# S9 acquisition architecture

## Purpose and status

This document fixes the cross-command boundaries before the command contracts are
expanded. It is design-only; there is no replacement acquisition package in tracked
code. Command-level signatures and UX flows belong to the linked command documents.

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
- The current `SecHttpClient.get_bytes()` materializes the response, so a bounded
  file-streaming client/broker operation is a prerequisite; S9 must not wrap the
  byte-returning method and call it streaming. The existing bytes-based
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
| `paths.py` | Resolve run, staging, distribution, and fixture roots; validate IDs and containment. |
| `schemas.py` | Lightweight versioned JSON/handoff contracts shared with S10. |
| `arrow_schemas.py` | Versioned Parquet schemas; imports the S6 target schema directly. |
| `models.py` | Immutable in-memory target, outcome, attempt, and staged-body records. |
| `work_order.py` | Validate the S6 bundle and write/read the immutable S9 work order. |
| `run_state.py` | Create and validate per-run state, append attempts, apply outcomes, and summarize status. |
| `projector.py` | Derive a run/work order from the pinned S6 plan without network access. |
| `runner.py` | Lock a run, schedule bounded target work, and preserve completed results. |
| `distribution_adapter.py` | Adapt acquisition work and outputs to shared distribution infrastructure. |
| `fixtures/` | Capture immutable response evidence, index cases, and replay offline. |
| `commands/` and `operator.py` | CLI dispatch and the interactive project/status/run consoles; [operator UX](operator.md) owns flow. |

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

Project, status, run, distribution, fixtures, and operator behavior are specified in
their command documents. These contracts must consume the shared types above rather
than redeclare their own versions.

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
  never payload bytes in JSON, SQL rows, Parquet metadata, or process IPC. The body
  and any separately staged bundle envelope remain available for the S10 handoff or
  explicit fixture capture. A matching S10 receipt permits cleanup without
  invalidating completed acquisition evidence.

## Resource and network policy

- Reuse SEC user agent, rate limit, retry, timeout, cache, and failure-ledger policy
  from the SEC settings and broker. Add only acquisition-specific settings where
  existing shared settings do not express a required bound.
- Stream to owner-generated paths and enforce the response-byte ceiling on bytes
  actually received after content decoding. `Content-Length` is only an early
  rejection hint. Oversize and partial responses never become acquired outcomes.
- Derive worker and memory budgets from `derive_resources()` and
  `auto_worker_count()`; keep both submitted work and in-flight bodies bounded.
- The shared broker owns pacing and failure accounting. Distributed mode must not
  silently multiply the effective SEC request rate across worker hosts; see the
  distribution contract's broker-coordination requirement.

## Required decision before distributed implementation

The local run path shares one SEC broker and its configured rate limiter across
workers. Separate worker hosts each own an independent broker; the SEC setting is
machine-local, so those hosts cannot claim one aggregate limit. The first S9
implementation is local only. Live distributed execution remains deferred until
either a shared cross-host lease/service or an enforced per-host rate allocation is
selected; distribution design documents are not authorization to bypass this gate.
