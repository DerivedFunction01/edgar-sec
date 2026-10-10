# Document acquisition lifecycle and publication plan

## Purpose and status

This document is the end-to-end design contract for S9 acquisition, S10 processing,
worker bundles, transient run state, and durable acquisition-snapshot publication. It
fills the former gap between resumable acquisition runs and the S11 payload-store
decision. It is a plan, not evidence that the replacement pipeline or publisher is
implemented.

The plan uses Parquet for all published snapshot relations and payloads, with the
shared `infra.storage.dag` engine publishing immutable parts and advancing the pointer
last. Payloads are split between joinable binary-route and text-route Parquet
relations; there is no external CAS directory. The precise relation and lifecycle
contracts below replace the earlier open-ended alternatives in
[S11](../S11_payload_design.md); implementation still requires the representative
S9/S10 evidence and acceptance gates listed here.

Published snapshot data has one format: Parquet. The run-state ledger remains SQLite
for transactional resume, and the fixture store is SQLite with Zstandard-compressed
BLOBs written before insertion. Neither SQLite use is an alternate durable snapshot
payload format.

## Inputs and boundaries

`document_planning` is the target-discovery boundary. An S6 plan already pins the
catalog scope, optional inventory snapshot, target IDs, requested role/type, optionality,
retrieval mode, safe locator or exact sequence, and catalog-direct selection policy.
Acquisition validates and copies that self-contained bundle into its run work order; it
does not reopen the catalog plan, inventory snapshot, or profile, and does not repeat
matching or discover companion targets. A missing or unresolved S6 target is retained
as a skipped work-order row, not repaired by S9.

S9 resolves the declared locator into exact source and selected-body bytes. S10 consumes
only the body assigned by S9 and produces a deterministic processing result. S11
publication records those per-target results, slot evidence, and payload references in
an immutable acquisition snapshot. S5 remains the metadata inventory owner; no payload
or processing field is added to S5 or S6 schemas.

## End-to-end lifecycle

1. **Project.** Validate the S6 manifest and every declared part, then write one
   deterministic S9 run manifest and Parquet work order containing every S6 target.
   Pin plan ID/digest and schema versions; never copy S6 source files into mutable run
   state or reopen their upstream catalog/inventory sources.
2. **Acquire.** Schedule only executable work-order rows. Append each attempt, including
   failed attempts and lazy-index evidence, to run state. Atomically adopt a response
   only after the received-byte limit, digest, size, redirect scope, and extraction
   checks pass. Keep source-response and selected-body identities separate.
3. **Process.** Submit each acquired target to S10 with its immutable S6 role/type and
   the resolved S9 body reference. S10 emits one versioned metadata result per acquired
   target. It writes a distinct derived representation to a managed transient file only
   when the route creates one; an identity representation aliases the source digest.
   Processing failure does not rewrite the S9 outcome or request another target.
4. **Publish.** After local execution or verified worker import and S10 completion,
    validate the run and publish one immutable DAG node. Write every successfully
    acquired physical-slot body, including a successful initial slot later replaced by
    lazy resolution, plus non-identity derived representations into typed payload
    Parquet relations. Advance the acquisition branch pointer only
    after every relation and payload part validates.
5. **Retain or clean.** A successfully published run may clean transient files after
   validating its publication receipt. A run intentionally discarded without
   publication requires an explicit discard action. Run cleanup never removes fixture
    BLOBs, review artifacts, Parquet parts reachable from retained DAG roots, or active
    run state.

Acquisition, processing, and publication failures are independent. A processing error
does not refetch a body; a publication error does not rerun SEC requests or mutate the
immutable S6 plan. Each stage resumes from its own validated artifacts.

## Transient run schema and lifetime

All run paths are under `transient/document_acquisition/{run_id}/` and are resolved by
[`paths.py`](paths.md). The immutable `run_manifest.json` pins the S6 source bundle,
work-order digest, S9/S10/run-state schema versions, and selected processing policy.
The Parquet work order has one row for every S6 target and is never edited after
projection. The SQLite `state.sqlite` is the sole mutable target ledger; it uses
foreign keys, bound SQL parameters, transactions, and the versioned schema in
[`run/persistence.md`](run/persistence.md).

| Transient record | Grain | Required content | Explicitly excluded |
|---|---|---|---|
| `target_state` | One S6 `target_id` per run | Executability, current acquisition outcome, attempt count, last attempt, source/selected digests and run-relative file references, retryability | Body bytes, S10-derived text, absolute paths |
| `attempts` | One network or fixture attempt | Attempt kind, source, typed outcome, retry classification, sanitized requested/final locator, timestamps, response/selected digest, size and path references | Full headers, credentials, body bytes |
| `target_slot_resolutions` | One catalog-direct resolution | Selector, expected filing form, screen/evaluator evidence, index attempt/parser identity, matching rows, chosen physical slot, result | Inferred type evidence from a local screen; rewritten S6 row |
| `processing result` | One acquired target | Versioned status, route, representation, processor fingerprint, diagnostics, input/output digest and size | Full normalized text in SQLite or Parquet metadata |
| `handoff receipt` | One consumed target body | S9/S10 versions, run/target IDs, source and selected digests, consumed status | Permission by itself to delete bytes needed for snapshot publication |

The fetched response is written beneath `staging/incoming/`; a bundle-selected child
is written separately beneath `staging/selected/`. S10's non-identity output, when
needed for publication or S7 review, is a third owner-generated file under
`staging/processed/`. Every path is run-relative in persistent records. Process and
broker IPC carry paths, digests, sizes, and typed metadata, never payload bytes.

Attempt rows and target-slot resolutions are append-only; `target_state` is a current
projection. Processing results are immutable per run/target and replaceable only by a
new processing attempt with its own fingerprint. A matching `BodyConsumptionReceipt`
proves S10 read and verified the body; it does not alone authorize deletion. S9 retains
    each raw acquired slot body until the snapshot publisher confirms Parquet
    publication or the operator explicitly discards the un-published run. A full bundle
    response envelope can be removed after extraction unless explicit fixture capture
    committed it; extracted slot bodies remain until publication/discard.

Partial network files never become target state. After a worker/runner crash, resume
verifies the run manifest, state DB, attempt references, files, digests, receipts, and
processing result references before reuse. Corrupt or unreferenced partial files are
not successes; status is read-only, and cleanup is a separate locked operation.

## Worker bundle contract

The work unit is a bounded assignment of S6 target rows, not a legacy locator with a
fan-out of occurrence rows. An export contains a signed-by-digest bundle manifest,
the exact assigned work-order rows, run/plan/schema identity, request ceilings, chunk
identity, and only explicitly selected fixture evidence. It does not contain a mutable
catalog plan, S5 snapshot, profile rules, unrelated targets, credentials, or an
unbounded source artifact tree.

A worker validates the manifest, assignment, row digests, target executability,
locator scope, and policy before opening a client. It uses the same S9 transport,
retry, extraction, and catalog-direct recovery contracts as local execution. Its local
ledger is independent of the coordinator DB. The worker receipt binds completed
outcomes, attempt/resolution rows, and every returned body file by path, size, and
digest. Import verifies the complete receipt and all files before adopting any result;
replay of a valid import is idempotent and cannot overwrite an already committed
coordinator outcome.

The planned acquisition worker does not run S10 or publish a snapshot. Returned
successful slot bodies are adopted into coordinator-managed transient staging; S10 then
runs against the coordinator's validated S9 work order. A later processing-distribution
extension would need its own assignment and receipt contract. S9 distribution is not
implemented. It will use the common schema-v2 assignment and receipt contracts: work
and assignment identity are bound, and receipts list output paths, sizes, and SHA-256
hashes. Common import verifies receipt affinity and file integrity before the
acquisition adapter validates pipeline-specific outputs for adoption. Older bundle
formats are unsupported and require re-export.

SEC request pacing is host-local under each machine's configured settings/environment.
Cross-host rate coordination and checks are explicitly out of scope; no cluster-wide
rate limit is implied. This scope statement does not add a coordination prerequisite to
the planned acquisition integration.

## S10 processing result contract

There is one S10 result for each acquired target. Skipped, `not_filed`,
`required_missing`, ambiguous, and failed acquisitions have no processing request.
Processing uses the selected body's effective path/route and immutable S6 form/role;
it cannot query S5/S6, discover an index entry, change a target assignment, or call
back into S9.

The result pins `target_id`, `run_id`, selected source digest, route, representation,
processor fingerprint, status, diagnostics, and optional derived digest/size. The
fingerprint includes routing/profile, normalization, output-schema, and engine
versions. HTML source bytes and derived text are different representations. ASCII
text passthrough and validated XML may alias the source payload row; binary inputs
remain raw-only. PDF extraction remains outside this plan. Review artifacts are
explicit S7/S10 review outputs, not the durable payload snapshot.

The S10 worker verifies and processes the same opened file. It may write a derived
representation only to managed transient staging; JSON results and IPC never carry
the text body. If S10 fails after fully consuming a verified source, it records a
processing failure and receipt, but the source remains available for retry, review,
or publication. Admission refusal before reading or input integrity mismatch produces
no receipt and retains the acquired body.

## Durable snapshot schema and payload layout

The publisher is an acquisition-pipeline adapter over the shared append-only DAG
kernel, not a new snapshot engine. Every published relation and document body is stored
inside Parquet parts in `document_acquisition/snapshots/`; the DAG does not reference
an external payload directory. Payload rows carry a digest over uncompressed logical
bytes and join to slot/target/result relations by that digest. Duplicate bytes are
deduplicated within the relation parts without collapsing their occurrence links.

The v1 logical relations are:

| Relation | Grain and identity | Contents and update rule |
|---|---|---|
| `target_results` | `(run_id, target_id)` | Append-only S6 target provenance plus S9 outcome and optional `processing_id`; includes skipped and terminal missing/error outcomes so partial coverage is explicit. |
| `processing_results` | `(run_id, target_id, processor_fingerprint)` | S10 status, route, representation, diagnostics, input/output payload digests and sizes. A processor change appends a new result rather than overwriting history. |
| `content_identity_findings` | `(run_id, target_id, finding_id)` | Sparse, append-only content-versus-metadata diagnostics: pinned expected form, suspected content family/form, selected slot and body digest, evidence references, and evaluator fingerprint. This is not SEC slot-type evidence. |
| `acquisition_slots` | `(accession, sequence, observation_id)` | Physical sequence and the source evidence that supplied its locator. `observation_id` distinguishes refreshed index/bundle evidence; sequence 1 is not statutory type proof. Append evidence; never silently replace an observation. |
| `slot_payloads` | `acquisition_id` | Successful link from a physical slot observation to its acquired-body `payload_sha256`, byte size, route, and acquisition attempt. No row represents failed transport. Identical bytes share one payload row while each slot link remains. |
| `slot_types` | `type_evidence_id` | Sparse observed type evidence with source, source digest/reference, parser version, and observation time. No row is created from a local target screen or heuristic cover result. Conflicts remain distinct evidence. |
| `target_slot_selections` | `(run_id, target_id, resolution_id)` | The slot assigned to S10, selector and evidence references. Preserves initial sequence-1 and any lazy-index replacement independently of the target's requested role/type. |
| `acquisition_attempts` | `(run_id, attempt_id)` | Durable typed attempt provenance for published runs, including failed attempts and lazy-index request identity; no payload bytes or secrets. |
| `binary_payloads` | `payload_sha256` | Separate Parquet relation for `DocumentRoute.BINARY` inputs (`.pdf`, `.gif`, `.jpg`); stores exact source bytes and uncompressed size. |
| `text_payloads` | `payload_sha256` | Separate Parquet relation for all non-binary routes, including markup/HTML, rendered HTML, text, XML, paper, and unknown. Stores exact raw or derived payload bytes plus a UTF-8 string value when valid. A digest identifies one byte value, so identity representations reuse the same row. |

Published payload bytes are held only in the typed Parquet payload relations, not in
SQLite run state, JSON manifests, or worker receipts. All route types go to one of the two payload
relations: only `DocumentRoute.BINARY` enters `binary_payloads`; HTML/markup is a
text-route payload, not a binary-media payload. `text_payloads` preserves exact source
bytes even when they cannot be decoded as UTF-8 and exposes a string value when valid.
`slot_payloads`, `target_results`, and `processing_results` join to `payload_sha256`; a
distinct S10-derived representation has its own digest row, while an identity
representation reuses its source row. Each DAG snapshot has independent Parquet
relations for `binary_payloads` and `text_payloads`; optional join indexes are also
Parquet relations and use the same digest key. The complete bundle response is not copied
into the durable snapshot by default: it remains transient extraction input, while
explicit S9 fixture capture can retain the exact envelope for offline replay. Every
successfully acquired physical-slot body, including an initial slot later replaced by
lazy recovery, is retained in its payload relation. The target-selection relation
records which body S10 processed.

Payload relations use the repository Parquet contract: Zstandard compression and
128,000-row-group sizing, with bounded parts and resource-derived writer memory. The
uncompressed-byte digest and byte size are independent of Parquet's internal
compression. `DocumentRoute.BINARY` from `edgar_sec.domain.document.route` is the
storage-class boundary; `.html` is never classified as binary media.

Catalog-direct sequence-1 acquisition creates a physical slot/payload link only after
successful acquisition. `submitted_primary` creates no type row without independent
type evidence. `exact_form_with_lazy_index` creates `slot_types` rows only from
recognized index-row `document_type` or bounded SGML bundle-child metadata; local
screen results remain on `target_slot_selections`. S5 reconciliation may add
index-observed locator/type evidence from a pinned inventory snapshot without fetching
document bodies or invoking S10. Reconciliation writes acquisition-owned relations;
it never mutates the S5 snapshot.

Family-aware content findings are separate from `slot_types` and cannot rewrite the S6
target form or an accession's filing metadata. Reprocessing appends a finding tied to
the body and evaluator version. Planning may later surface prior findings as review
context, but using one to change a target requires a separately versioned planning or
operator decision; S6 does not silently consume S11 diagnostic rows.

## Snapshot publication and recovery

The publication operation consumes one validated S9/S10 run, including all worker
receipts already imported. Before creating a DAG node it:

1. Confirms the run/plan/schema identity, validates all declared files and result rows,
   and rejects duplicate target/run identities or paths outside owner roots.
2. Requires every work-order target to have a stable terminal disposition and every
   acquired target to have an S10 result. If any outcome is `failed`, `ambiguous`,
   `required_missing`, or processing-failed, publishing requires explicit
   `--allow-errors`; the manifest records counts and `complete_with_errors` rather
   than presenting the snapshot as complete.
3. Streams metadata rows and selected source/derived payloads into bounded staging
   Parquet writers. Verify exact uncompressed digest/size before accepting each row;
   binary-media and text-route rows go to separate relation parts. Payload-row identity
   deduplicates identical content without dropping slot/target joins.
4. Writes deterministic DAG relation parts and a manifest pinning the parent snapshot,
   run ID/digest, S6 target-plan ID/digest, relation schema versions, counts, part
   digests, and referenced payload digests. The snapshot identity is derived from
   parent identity, canonical run-evidence digest, and schema versions. Re-publishing
   the same run is idempotent.
5. Validates referential integrity, row counts, payload-row reachability,
   uncompressed-byte hashes, and
   deterministic relation fingerprints. A stale expected parent or any validation
   failure leaves the active branch pointer unchanged; retry rebuilds from validated
   run files without SEC requests.
6. Atomically publishes the immutable node through `infra.storage.dag` and advances
   the selected branch pointer last. Only after a matching publication receipt is
   durable may the run-cleanup command remove source, selected, and processed staging.

The default branch is `main`; branch-tip compare-and-swap prevents concurrent
publishers from silently losing updates. Immutable snapshots remain readable by ID.
Snapshot metadata queries do not materialize payload columns unless requested. DAG
compaction carries forward live relation and payload rows; retention prunes only parts
unreachable from branches, tags, or explicit pins, never by file age alone.

## CLI and operator lifecycle

The local acquisition surface becomes:

```text
acquisition project --target-plan <id>
acquisition status --run-id <id>
acquisition run --run-id <id> [--retry-failures]
acquisition process --run-id <id>
acquisition publish --run-id <id> [--branch <name>] [--allow-errors]
acquisition query --snapshot <id|current> [target/slot filters]
acquisition fixture capture|list|replay ...
acquisition distrib export|worker|import ...   # planned; common CLI uses --work-id
```

The interactive operator shows Project, Status, Run, Process, and Publish as distinct
actions. Run requires explicit network authorization; Process and Publish are local.
Publish previews target outcome counts, error classes, parent snapshot, and payload
bytes to adopt before asking for confirmation. Distribution Import only adopts verified
run results; it never implicitly processes, publishes, or captures fixtures.

## Difference from legacy `document_storage`

| Legacy behavior | Planned replacement |
|---|---|
| Work is locator-keyed and fans out to `FilingOccurrence` rows; one acquired body can be copied across synthetic CIK occurrences. | Work is an explicit S6 target request. `target_id` identifies intent; accession/sequence identifies a physical slot; S5 source-CIK edges are not copied into target occurrences. |
| Fetch, body selection, normalization, evaluator, and row construction are coupled in the worker. | S9 acquisition, S10 processing, and S11 publication have separate versioned input/output boundaries and recover independently. |
| Bundle extraction chooses one selected child during fetch and may infer/recover a primary or fetch an exhibit from evaluator outcomes. | S6 declares the target and exact sequence. Only the pinned catalog-direct lazy-index selector may resolve a replacement slot, using observed index type evidence; S10 cannot initiate more work. |
| `raw_payload` can mean normalized UTF-8 text, original bytes, or pass-through data; raw and normalized content share a row shape. | Source response, selected raw body, and derived representation have distinct digests, roles, and lifetimes. Typed Parquet relations store payload bytes and metadata with stable join keys. |
| Locator-chunk sidecars and a combined checkpoint schema are used for resume. | Immutable S6 work-order Parquet plus a versioned per-run SQLite target/attempt/resolution/processing ledger. Completed target evidence is independently reusable after restart. |
| Snapshot rows are keyed by occurrence/document identity and use quarter-bucketed index/payload parts. | Acquisition snapshot rows are run/target and accession/physical-slot evidence, published as DAG Parquet deltas; separate binary and text payload relations join by digest. |
| Legacy fixtures and old snapshot payload layout drive replay and viewer discovery. | S9 fixture SQLite retains explicit source responses for offline evidence; acquisition snapshots publish only planned selected bodies and distinct S10 representations. Viewer and old artifact migration remain explicit retirement work. |

Retain bounded worker execution, integrity checks, explicit fixture replay, immutable
publication, and pointer-last safety as general invariants. Do not port legacy
candidate gates, occurrence expansion, selected-index schemas, implicit delegation,
raw/normalized payload ambiguity, or old artifact layouts.

## Implementation sequence and acceptance

1. Complete shared S9/S10 schemas, paths, streaming transport, exact SGML extraction,
   run-state projection, and fixture store.
2. Implement the local S9 runner and the acquisition-only worker bundle/import
   contract. Keep live remote execution disabled until its rate gate passes.
3. Implement S10 processing and the fixture-only S9-to-S10 vertical gate, including
   byte identity, processing failures, memory admission, and receipt semantics.
4. Implement the acquisition DAG relation specs, binary/text Parquet payload relations, metadata-only S5
   reconciliation adapter, snapshot writer/query surfaces, and run publication
   receipt/cleanup protocol.
5. Validate with the representative fixture corpus; then authorize the durable
   publisher and verify legacy consumer/artifact migration separately before retiring
   `document_storage`.

Acceptance covers deterministic identical-run publication; duplicate payload rows shared
by digest with distinct slot/target references; bundle envelope versus selected-child
identity; selectors and sparse type rows; observed conflicting index evidence;
S5-only metadata reconciliation; stale-parent refusal; interruption at every copy,
manifest, node-install, and pointer-update boundary; corrupt/missing payload parts or
digest mismatches;
explicit error publication; worker receipt tampering/replay; and cleanup refusal before
publication adoption. The full repository test suite is not implied by the roadmap;
focused mirrored tests and the configured quality gate remain mandatory.

## Remaining gates

- S5 relation-schema ownership and the bounded S6 source adapters remain upstream
  implementation gates for a full inventory-backed vertical run; the acquisition
  pipeline still consumes a conforming immutable S6 bundle without reopening them.
- S0 historical parser acceptance and live SEC rollout remain unchanged.
- Acquisition distribution remains unimplemented; cross-host SEC rate coordination
  and checks are out of scope.
- PDF extraction, XBRL package execution, taxonomy activation, old artifact migration,
  viewer cutover, and `document_storage` deletion are outside the snapshot publication
  implementation itself and require their stated independent evidence/retirement gates.
