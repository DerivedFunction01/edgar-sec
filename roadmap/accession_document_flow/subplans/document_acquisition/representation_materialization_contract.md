# Representation materialization and reuse contract

**Status: design v1 for iteration; implementation remains gated.** This contract defines
the S6 operation inputs, S9 work/run records, source reuse, and Parquet snapshot
relations as one versioned chain. It does not enable M7, M9, or S11 publication.

## Decision

Add an acquisition-owned representation relation that maps a logical output to a
content-addressed payload. Do not put accession or sequence on the payload row and do
not use the S6 `target_id` as the cross-plan key. Keep accession/sequence-to-source
mapping, source-to-payload mapping, and operation-to-representation mapping separate.
Accession-to-CIK facts and observed statutory type remain independent relations.

The resulting join is:

```text
plan target -> stable logical_document_id -> operation result
                                      operation result -> representation -> payload digest
                                      operation result -> input source(s)
                                                       source -> accession/sequence observation
                                                       source -> raw payload digest
```

Digest deduplication applies only to payload bytes. It must not collapse source,
operation, representation, or accession/sequence provenance rows.

## Version cut

This design generation pins S6 bundle v4 (target relation v1 plus three operation
relations v1), S9 acquisition contract v2, run manifest v2, work-order relation set v2,
SQLite run state v3, handoff/receipt schema v2, and acquisition snapshot relation set
v1. Readers refuse older schemas for this operation-aware path; code changes and tests
are a later implementation step.

## Versioned inputs, work, and run

### S6 bundle input

The input is a normalized four-relation bundle. `targets` keeps schema v1. The new
`target_operations`, `source_requests`, and `operation_inputs` relations are schema v1
under S6 bundle schema v4. Their exact grains and request semantics are specified in
[S6 specs](../document_planning/specs.md).

Each target has one `target_operations` row for each operation in the closed vocabulary.
The row separates `requested` from `support_status`; it pins capability, handler and
output metadata. `operation_inputs` links each requested/supported operation to its
source request. Version 1 restricts each operation to the target's single primary source
request. A capability requiring another locator or multiple input bodies is unsupported
until a versioned S6/S9 input and source-state extension exists.

### S9 immutable work bundle

The work order is also a relation set, not a flattened target-operation Cartesian
product. Work-order schema v2 contains:

| Relation | Key | Added or copied columns |
|---|---|---|
| `work_targets` | `target_id` | All S6 target columns; `executable`, `skip_reason`, and nullable `chunk_id`. One row per S6 target, including skipped targets. |
| `work_operations` | `(target_id, operation)` | Exact S6 request/support rows and their `operation_id` values. |
| `work_source_requests` | `source_request_id` | Exact validated S6 source request rows. |
| `work_operation_inputs` | `(operation_id, input_ordinal)` | Exact S6 operation-to-source links. |
| `work_chunks` | `chunk_id` | Zero-based chunk ordinal, target count, and digest over ordered member target rows and their operation/source/input rows. |

All relations are Parquet parts under `work_order/{relation}/part-*.parquet`. The run
manifest pins each relation schema version and each part's relative path, row count,
byte size, and digest. `chunk_id` is stored on executable `work_targets`; skipped rows
have no chunk. Chunk boundaries are created by sorting executable target IDs and
grouping by the pinned `runtime.chunk_size`. A target and all its operation/source rows
are one indivisible work unit. Chunk status is derived from target state; SQLite does
not duplicate immutable chunk membership.

The chunk digest covers the exact work for those targets, not execution order. Worker
assignments bind `run_id`, work digest, assignment ID, and chunk IDs through the common
distribution protocol. A worker bundle includes only assigned relation rows and any
verified source payloads reused from the pinned base snapshot. S9 workers acquire inputs
only; S10 operations execute as a separate processing action.

### Run identity and mutable ledger

The immutable run manifest schema v2 pins the S6 bundle/digest and all relation schema
versions; work-order schema v2 and part descriptors; chunking algorithm/version and
size; acquisition contract and response-byte ceiling; source mode and fixture identity
when replaying; run-state schema v3; and publication branch/base snapshot ID/digest.
The pinned base is both the publisher's expected parent and the only source-reuse
lineage searched. A null base is valid only for an empty branch. Project resolves/pins
the branch tip once; workers, `run`, and `process` never follow a moving branch pointer.

`run_id` derives from the S6 plan digest, acquisition/work/run-state schema versions,
branch/base snapshot, chunking settings, source mode/fixture ID, and acquisition
response ceiling. The manifest digest additionally covers all work relation parts and
counts. Worker count, request pacing, completion order, and retry attempt numbers are
not run identity. Re-projecting identical pins is idempotent; changing any work-affecting
input creates a new run ID. Publishing compares the branch tip with the pinned base;
a stale base requires a new projected run.

The mutable SQLite state schema v3 retains the existing acquisition tables and adds:

| Table | Key / grain | Current projection or history |
|---|---|---|
| `operation_state` | `operation_id` | S6 requested/support status plus `not_requested`, `unsupported`, `pending`, `blocked`, `available`, or `failed`; latest attempt and representation IDs; retryability and stable reason code. |
| `operation_attempts` | `operation_attempt_id` | Append-only target/operation attempt, input fingerprint, handler/capability/options versions, outcome, reason code, output digest/size and optional run-relative staged path. `representation_reuse` attempts point to a verified parent representation and have no output path. |

`target_state` remains the current acquisition outcome per target; `attempts` and
`target_slot_resolutions` remain append-only. Snapshot source reuse adds an acquisition
attempt with origin `snapshot_reuse`, the reused snapshot ID, stable source asset ID, and
verified payload digest; it makes no HTTP request and does not rewrite S6 selection.
`operation_state` is separate from `target_state`: a target can be acquired while one
render fails, and a failed acquisition can block requested render operations without
rewriting their S6 intent. `run --retry-failures` retries acquisition only;
`process --retry-failures` retries operation failures only. Before invoking a handler,
process may reuse a parent representation only if logical document, operation, exact
input source/digest, capability/handler/options versions, and output kind all match.
That produces an available `representation_reuse` attempt without rendering.
Worker/chunk assignment and receipt metadata stay in common distribution bundles;
imported body outcomes enter ordinary acquisition attempts in a transaction per
validated chunk.

Snapshot publication refuses pending operation rows. `not_requested`, `unsupported`,
`blocked`, `failed`, and `available` remain distinguishable; a `failed` attempt does not
erase an older successful representation.

## Stable identities

- `source_asset_id` identifies one logical source locator independently of plan and content:
  SHA-256 of canonical JSON `[accession, source_key]`. `source_key` is the validated
  `direct:<canonical archive path>` key or a typed
  `bundle:<canonical archive path>#seq=<sequence>` key. Path case is preserved and
  query/fragment/userinfo are excluded by locator validation. A source digest is
  deliberately not part of identity so changed bytes remain a new observation for
  the same physical source.
- `logical_document_id` identifies the requested document independently of its plan:
  SHA-256 of canonical JSON `[accession, request_id, planned_source_key]`, using the
  same typed source-key format as `source_asset_id`. Distinct S6
  candidates remain distinct. A later plan joins to the same logical document only when
  accession, role/type request, and planned source key match. A later lazy-index
  replacement changes the actual source asset, not the target's planned identity.
- `representation_id` identifies a successful operation output, not its bytes:
  canonical identity includes `logical_document_id`, operation, ordered input-source
  identities and payload digests, output kind, capability/handler IDs and versions,
  options digest, and output digest.
  Equal output digests may be shared while distinct representation rows preserve
  provenance.
- S6 `source_id`, `operation_id`, `target_id`, and `plan_id` remain request provenance.
  They are plan-dependent and are never used as stable source or representation identity.
  Acquisition maps each S6 source request to a `source_asset_id` after resolving its
  canonical source key.

For sequence-based sources, the existing accession/sequence observation relation maps
to `source_asset_id`; it is not itself the content key. Direct sources with no observed
sequence remain addressable by their validated archive-relative path. `slot_types`
remain sourced observations and do not become source identity or renderer input.

## Proposed snapshot relations

These are normalized acquisition-owned Parquet relations, not a requirement for one
file per table per snapshot. Each DAG node writes only changed relation parts; the
manifest records part digests, sizes, counts, and key bounds. `RelationSpec` resolves
the ancestor deltas by declared key/merge policy, and queries join the resolved
relations as needed. A prejoined projection is optional and rebuildable, never the
source of truth. This is relation-set schema v1; snapshot manifests pin that version.
The listed key fields are non-null unless a field is explicitly marked optional below.
IDs/digests are strings, flags are booleans, counts/sizes/sequences use `int32` or
`int64`, and event times are UTC timestamps.

| Relation | Grain / key | Merge | v1 fields and role |
|---|---|---|---|
| `accession_ciks` | `accession` | Upsert; conflicting CIK refused | `cik:string`; filing identity stays separate from targets and payloads. |
| `source_assets` | `source_asset_id` | Upsert; identity fields immutable | `accession:string`, `source_key:string`, `source_kind:string`, `retrieval_mode:string`, `canonical_path:string?`. Stable across plans; no payload bytes or physical sequence column. |
| `acquisition_slots` | `(accession, sequence, observation_id)` | Append | `sequence:int32`, `observation_id:string`, `source_asset_id:string`, `locator:string`, `retrieval_mode:string`, `observed_at_utc:timestamp`. Maps a physical sequence observation to a stable source; no type inference. |
| `slot_types` | `type_evidence_id` | Append | `accession:string`, `sequence:int32`, `observation_id:string?`, `statutory_type:string`, `evidence_source:string`, `evidence_ref:string`, `source_digest:string?`, `parser_version:string`, `observed_at_utc:timestamp`. |
| `logical_documents` | `logical_document_id` | Upsert; identity fields immutable | `accession:string`, `request_id:string`, `planned_source_key:string`, `target_role:string`, `target_type:string`. Distinct planned candidates remain distinct. |
| `target_results` | `(run_id, target_id)` | Append | Full S6 target provenance, `logical_document_id:string?`, S9 `outcome:string`, `status_reason:string?`, selected source asset/digest/size when acquired. |
| `target_slot_selections` | `(run_id, target_id, resolution_id)` | Append | `accession:string`, `sequence:int32`, `observation_id:string?`, `source_asset_id:string?`, selector/result and evidence refs. |
| `acquisition_attempts` | `(run_id, attempt_id)` | Append | Target/source-request/source-asset IDs, attempt kind/origin, typed outcome/retryability, sanitized locator, timestamps, HTTP evidence, source/selected digests and sizes, worker assignment ID. No payload bytes. |
| `source_payloads` | `(source_asset_id, payload_sha256)` | Upsert by exact content identity | Link from a stable source to a successfully retained raw payload. Route, size, and attempt provenance stay in `acquisition_attempts`/`payload_index`. If one source asset has more than one distinct digest in the pinned base lineage, S9 treats reuse as ambiguous and follows the new S6 request. |
| `operation_results` | `(run_id, operation_id)` | Append | `target_id`, `logical_document_id`, operation/request/support state, terminal materialization status, planned `source_request_id?`, capability/handler versions, latest attempt, reason/retryability, representation ID. `pending` is transient and not publishable. |
| `operation_attempts` | `(run_id, operation_attempt_id)` | Append | `operation_id`, ordinal, attempt kind (`identity`, `transform`, `representation_reuse`), input fingerprint, handler/capability/options versions, `available`/`failed`, error code, input/output digests and sizes, optional staged path. |
| `representations` | `representation_id` | Upsert by exact identity | `logical_document_id`, operation, output kind, capability/handler/options versions, input fingerprint, output payload digest/size and route. No bytes or accession/sequence copy. `raw` aliases the source payload digest. |
| `representation_inputs` | `(representation_id, input_ordinal)` | Upsert; conflicting row refused | `source_asset_id:string`, exact input `payload_sha256:string`, semantic input role. |
| `payload_index` | `payload_sha256` | Upsert; class/size immutable | `storage_class:string` (`binary` or `text`), `byte_size:int64`. Enforces one physical storage row for a digest across typed payload relations. |
| `binary_payloads` | `payload_sha256` | Upsert; bytes must match digest | `byte_size:int64`, `payload_bytes:large_binary`; contains a row only when `payload_index.storage_class=binary`. |
| `text_payloads` | `payload_sha256` | Upsert; bytes must match digest | `byte_size:int64`, `payload_bytes:large_binary`, `text_value:string?` when valid UTF-8; contains a row only when `payload_index.storage_class=text`. |

Within each node, every primary key is unique before its relation parts are written.
The publisher validates these cross-relation references over the resolved parent plus
node:

- `acquisition_slots.source_asset_id` and `source_payloads.source_asset_id` resolve to
  `source_assets.source_asset_id`.
- `target_results.logical_document_id` resolves to `logical_documents` when non-null;
  `target_slot_selections` resolves to its target and observed slot evidence.
- `source_payloads.payload_sha256`, operation outputs, and representation inputs
  resolve through `payload_index` to exactly one matching typed payload row.
- `operation_results` retains the S6 operation ID and resolves to its target result;
  `available` requires a representation. Each representation resolves to one logical
  document and output payload; each input resolves to one source asset and exact input
  payload.

An upsert key may repeat in a descendant only when the row satisfies the relation's
identity validator. An accession cannot change CIK, a source/logical-document ID cannot
change locator identity, a digest cannot change storage class or bytes, and a
representation ID cannot change output or input provenance. Append relations reject
duplicate keys within one node and preserve distinct evidence across nodes.

`payload_index` chooses exactly one typed payload relation per digest. For a new digest,
the class is `binary` if any source use is `DocumentRoute.BINARY`; otherwise it is
`text`. Once present in the base lineage, the class cannot change. Publication verifies
one and only one matching typed row, byte size, and uncompressed SHA-256. Thus identical
bytes referenced from binary and text operations still occupy one physical payload row.
This storage class is not the source route; each source and representation retains its
own route metadata.

The old run-scoped `slot_payloads` view is projected by joining
`acquisition_slots.source_asset_id` to `source_payloads`; it is not a second base
relation. `accession_ciks` and `slot_types` remain independent joins. The payload
relations contain only digest-keyed bytes and byte metadata.

`operation_results` is run-scoped because “not requested” describes one plan/run, not
the lifetime of a logical document. A later plan that omits `render_to_txt` must not
hide or delete an earlier text representation. Published rows have terminal status;
attempt history is append-only. A representation is available only when its output
payload verifies. Failure or a later unrequested operation never erases a prior valid
representation.

Typical projections are assembled from these relations rather than stored repeatedly:

- Filing identity: `accession_ciks` joined to `logical_documents` / `target_results` by
  accession.
- Physical slot and observed statutory type: `acquisition_slots` joined to
  `slot_types` on accession, sequence, and observation evidence.
- Available source body: `acquisition_slots` or `logical_documents` joined to
  `source_payloads`, then to the correct typed payload relation by digest.
- Requested outputs: `target_results` joined to `logical_documents`,
  `operation_results`, `representations`, and `representation_inputs`; payload reads
  join by digest only when requested.

This resolves the raw-then-render case without a special combined table: Plan A adds a
raw representation and `render_to_txt=not_requested`; Plan B adds a new run's request,
reuses the parent-lineage `source_payloads` row, and adds a distinct render
representation. Both representations remain reachable in the projected snapshot.

The v1 relation set and merge strategies above are the input to mirrored Arrow schema
and `RelationSpec` definitions. The DAG engine already supports immutable parts and
relational resolution; this design adds domain schemas, not a new snapshot mechanism.

## Fixture boundary

The fixture store is intentionally not this schema: it remains SQLite case metadata
plus digest-deduplicated, compressed exact response bodies. Its case key and evidence
remain tied to capture, target-plan, target, and attempt identities; it has no operation
status or rendered-representation rows. The raw-then-render acceptance case can capture
the Plan A source once, use that fixture to build a temporary raw-only Parquet snapshot,
then verify Plan B reuses the snapshot's `source_payloads` row and publishes the render.
Plan B must not need a second fixture case or synthetic fixture operation record.

If fixtures later need to replay one source response against multiple plan-dependent
target IDs without an intermediate snapshot, a stable-source fixture lookup would be a
separate fixture-store contract. It should not be implemented by copying snapshot
operation statuses into fixture SQLite.

## Status and reuse rules

- `not_requested` means the plan did not ask for the operation. It is not a failed,
  unsupported, or available result.
- `unsupported` means the pinned family/path capability catalog did not support the
  requested operation. It is not a document absence and cannot be retried under the
  same capability version. A new capability version can resolve it again.
- `pending` means the plan requested a supported operation but has no terminal
  operation attempt yet.
- `failed` is an append-only attempt result. It does not imply unsupported and does
  not prevent a later explicit retry.
- `available` requires a verified representation row and payload-index row whose
  digest and size match exactly one typed payload row. It records the operation and
  handler version even when its digest aliases another representation.
- An existing raw payload is reusable only when the new plan resolves to the same
  stable `source_asset_id`, exactly one distinct payload digest is available for it in
  the pinned base lineage, and the retained bytes verify. Multiple digests are an
  ambiguous source version, so S9 follows the new S6 request rather than choosing one.
  Reuse does not reselect a target or promote diagnostic evidence into a locator.
- An available rendered representation is reusable only when logical document,
  operation, input-source identities/digests, output kind, capability version, handler
  version, and relevant options match. A changed handler or input requires a new
  materialization; old rows remain immutable.
- Raw-only history does not satisfy a later render request. The later plan records the
  render as pending and runs it from the eligible retained source. If no eligible
  source exists, S9 follows the new plan's source request. A prior failed render is
  retried only by its explicit retry policy; unsupported and not-requested are never
  interpreted as successful output.

## Renderer boundary and family capabilities

`render_to_txt` and `render_to_xml` are representation/export operations. They must
not call `normalize_document` or inherit its cover detection, checkmark removal,
reflow, or table-repair behavior. Raw bytes remain a separately addressable
representation even when an export is lossy.

`render_to_xml` is a family-specific transform with a declared input path and output
representation. For a family that registers the capability, the input is the primary
`edgar.htm` source and the output is XML. It does not probe for or fetch a `.xml` bundle
sibling, copy an archive-root XML file as if that were rendering, or perform semantic
XML/XBRL parsing. Unregistered family/path combinations are recorded `unsupported`.
The versioned capability entry pins family, role/type, path facts, source strategy,
handler ID/version, output kind, and fidelity contract. Only explicitly registered
families/forms can request an available render.

`render_to_txt` likewise uses its registered representation handler over the planned
input bytes, not the filing normalizer. Operation failure is independent: a failed
render leaves raw available and does not trigger another locator or mutate S6 target
selection.

## Defining lifecycle case

1. Plan A requests only `raw`; S9 acquires a source and publishes its raw
   representation, source-to-payload link, and `render_to_txt=not_requested` status.
2. Plan B has a new plan-dependent target ID but resolves the same accession,
   request ID, and `source_asset_id`. The retained raw payload passes reuse checks, so S9
   does not refetch. Plan B records `render_to_txt=pending`, executes the pinned
   renderer on that verified source, then publishes a distinct representation row and
   payload link. The new snapshot retains both raw and rendered representations.
3. If the source asset identity differs or its retained bytes fail integrity checks, S9
   performs the new plan's source request. If the renderer fails, raw remains
   available and the operation attempt is `failed`; it is not reported as
   unsupported or silently skipped.

This case belongs in the defining DAG/snapshot acceptance test. It does not enable the
unfinished M7 process/publish path or the M8/M9/S11 gates.
