# Document acquisition lifecycle and publication plan

## Purpose and status

This document is the end-to-end design contract for S9 acquisition, S10 operation
materialization, worker chunks, transient run state, and durable Parquet snapshot
publication. It fills the gap between resumable acquisition runs and the S11 payload
store. It is a plan, not evidence that the versioned replacement pipeline or publisher
is implemented.

The S9 selected-body reference and immutable consumption-receipt boundary is implemented
and covered by an offline fake-consumer acceptance test. An initial offline S10 worker
and schema-neutral in-memory terminal-result preflight also exist. Operation-result
persistence, receipt-driven run-state projection, S11 adoption, publication, and cleanup
authorization remain unimplemented.

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

`document_planning` is the target and operation-intent boundary. Operation-aware S6 v4
pins the target relation plus target-operation, source-request, and operation-input
relations. Acquisition validates and copies all relations into its run work bundle; it
does not reopen the catalog plan, inventory snapshot, or profile, and does not repeat
matching or discover companion targets. A missing or unresolved S6 target is retained
as a skipped work-order row, not repaired by S9.

For each target, S9 follows the retrieval mode and observed sequence pinned by S6. It
does not compare child/index size, full-submission bundle size, or S1-reported size;
group target requests into one bundle download; or switch an ordinary direct failure to
the bundle. Review-run and fixture evidence establishes that positive numbered child names
map to accession-prefixed archive leaves; a valid pinned leaf is a direct locator, and
`0001` is not inherently a placeholder. Exact primary `0000.txt`/`.htm` names remain
placeholder signals and require an observed bundle URL and positive sequence. An indexed
`0001.txt`/`.htm` primary without a usable prefixed link may use its observed sequence and
bundle URL; catalog-only `0000` targets remain unresolved. The separately pinned
catalog-direct lazy-index contract is not an ordinary direct-failure fallback.

S9 resolves the declared source and selected-body bytes. Any future reuse is restricted
to the same logical target and source; it cannot share a bundle response across targets.
S10 consumes only
the body assigned by S9 and independently materializes each requested supported
operation. S11 publishes target outcomes, operation outcomes, slot evidence, stable
source references, representations, and payloads in an immutable acquisition snapshot.
S5 remains the metadata inventory owner; no payload or processing result is added to
S5 or S6 schemas.

## End-to-end lifecycle

1. **Project.** Validate the complete S6 v4 relation set and every declared part. Pin
   the exact base snapshot (or null), response-byte ceiling, chunking settings, and
   relation schemas in one run manifest. Write immutable Parquet relations for all
   targets, operations, source requests, operation inputs, and chunks.
2. **Acquire.** Schedule each executable target independently and follow its pinned
   S6 source request. Do not compare target sizes, coalesce multiple bundle targets,
   or reuse one bundle response across targets. Append attempts and any explicitly
   authorized catalog-direct lazy-index evidence.
   Atomically adopt direct or selected bytes only after byte-limit, digest, size,
   redirect, and extraction checks. A worker chunk contains all relations for its
   assigned targets and per-target source payloads. A bundle response is never
   shared across targets.
3. **Process.** Submit each acquired target and its S6 operation set to S10. S10 emits
   one terminal result per operation and an append-only attempt for each execution.
   Raw is an identity representation; renders are separate outputs. Processing failure
   does not rewrite the S9 target result, select another locator, or erase an older
   successful representation.
4. **Publish.** After local execution or verified worker import and completion of all
   supported requested operations, validate the run and publish one immutable DAG node.
   Write retained source payloads and successful operation representations to typed
   payload Parquet relations. Advance the branch pointer only after every relation and
   payload part validates.
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
[`paths.py`](paths.md). The immutable `run_manifest.json` pins the complete S6 relation
bundle, work relation parts, base snapshot, chunking/acquisition policy, and
S9/S10/run-state schemas. The Parquet work order is a normalized relation set and is
never edited after projection. SQLite `state.sqlite` is the sole mutable run ledger; it uses
foreign keys, bound SQL parameters, transactions, and the versioned schema in
[`run/persistence.md`](run/persistence.md).

| Transient record | Grain | Required content | Explicitly excluded |
|---|---|---|---|
| `target_state` | One S6 `target_id` per run | Executability, current acquisition outcome, attempt count, last attempt, selected source asset/digest and run-relative file reference, retryability | Body bytes, S10-derived output, absolute paths |
| `attempts` | One source acquisition/reuse or lazy-index attempt | Source request/asset IDs, origin, typed outcome, retry classification, sanitized locator, timestamps, response/selected digest, size and paths | Full headers, credentials, body bytes |
| `target_slot_resolutions` | One catalog-direct resolution | Selector, expected filing form, screen/evaluator evidence, index attempt/parser identity, matching rows, chosen physical slot, result | Inferred type evidence from a local screen; rewritten S6 row |
| `operation_state` | One S6 `operation_id` | Request/support state, current status, latest attempt and representation, retryability and stable reason code | Body bytes, rendered output bytes, absolute paths |
| `operation_attempts` | One S10 operation attempt | Input fingerprint, handler/capability/options versions, outcome, reason, output digest/size and run-relative path | Rendered output bytes |
| `handoff receipt` | One target body per processing run | Receipt schema v2, run/processing-run/target IDs, source asset and selected digest, optional source-response digest, UTC consumption time | Permission by itself to delete bytes needed for snapshot publication |

The runner writes response, index, reused-source, selected, and per-operation output
files beneath `staging/`. Every persisted path is run-relative. Process and broker IPC
carry paths, digests, sizes, and typed metadata, never payload bytes.

Acquisition and operation attempts/resolutions are append-only; target and operation
state are current projections. Every operation retry has its own input fingerprint.
A matching `BodyConsumptionReceipt` records a consumer assertion bound to committed S9
source identity; it does not independently prove consumption or authorize deletion.
S9 retains selected source bodies until the publisher confirms Parquet publication or
the operator explicitly discards the unpublished run. A full bundle response can be
removed after extraction unless fixture capture committed it.

Partial network files never become target state. Run validation checks the manifest,
work order, and state structure; the handoff service separately verifies staged bytes
and receipt sidecars. Runner cleanup removes only unreferenced staging entries, not
committed selected bodies. Status is read-only.

## Worker bundle contract

The work unit is a bounded assignment of S6 target rows, not an operation row or a
legacy locator with a fan-out of occurrence rows. An export contains a digest-pinned
bundle manifest, all relation rows for assigned targets, run/plan/schema identity,
request ceiling, chunk identity, verified reused-source payloads, and only explicitly
selected fixture evidence. It does not contain a mutable
catalog plan, S5 snapshot, profile rules, unrelated targets, credentials, or an
unbounded source artifact tree.

A worker validates the manifest, assignment, relation digests, target executability,
locator scope, and policy before opening a client. It uses the same S9 transport,
retry, extraction, and catalog-direct recovery contracts as local execution. Its local
ledger is independent of the coordinator DB. The worker receipt binds completed
outcomes, attempt/resolution rows, and every returned body file by path, size, and
digest. Import verifies the complete receipt and all files before adopting any result;
replay of a valid import is idempotent and cannot overwrite an already committed
coordinator outcome.

The acquisition worker does not run S10 or publish a snapshot. Returned source bodies
are adopted into coordinator-managed transient staging; S10 runs against the
coordinator's validated work relations. Processing distribution remains a separate
extension. S9 distribution uses common schema-v2 assignments and receipts: work and
assignment identity are bound, and receipts list output paths, sizes, and SHA-256
hashes. Import validates the complete chunk before adopting it. Older bundle formats
are unsupported and require re-export.

SEC request pacing is host-local under each machine's configured settings/environment.
Cross-host rate coordination and checks are explicitly out of scope; no cluster-wide
rate limit is implied. This scope statement does not add a coordination prerequisite to
the planned acquisition integration.

## S10 operation result contract

There is one S10 terminal result per S6 operation row. A skipped or unresolved target
blocks its requested supported operations. An unrequested operation is `not_requested`;
a requested capability miss is `unsupported`; a supported operation with unavailable
input is `blocked`; execution ends `available` or `failed`. `pending` is transient and
cannot be published. Processing uses only the exact source asset and digest assigned by
S9; it cannot query S5/S6, discover an index entry, change a target assignment, or call
back into S9.

Each operation result pins `run_id`, `operation_id`, stable logical-document identity,
status, capability/handler/options versions, input fingerprint, representation ID, and
error reason. Each attempt adds an ordinal and exact input/output digests, sizes, and
run-relative staged path. Raw is an identity representation. `render_to_txt` chooses a
family/route-specific renderer before the generic normalizer fallback for eligible
text/HTML sources; `render_to_xml` chooses a family-specific transform before an
evidence-backed generic transform. PDF extraction remains unavailable. Review artifacts
remain explicit S7/S10 outputs, not snapshot source tables.

A processor-version change does not retire all outputs using the old version. A plan may
explicitly supersede only selected forms/families, operations, and prior processor
versions in a new immutable snapshot. The selective supersession plan option and pruning
behavior are not implemented.

The S10 processor verifies the same opened source for all operations assigned to its
target request. It writes one derived file per successful non-identity operation to
managed transient staging; JSON results and IPC never carry payload bodies. Failure of
one operation leaves source and sibling operation results available. Handoff receipts
bind the stable source asset and selected digest; they do not authorize cleanup.

## Durable snapshot schema and payload layout

The publisher is an acquisition-pipeline adapter over the shared append-only DAG
kernel, not a new snapshot engine. Every published relation and document body is stored
inside Parquet parts in `document_acquisition/snapshots/`; the DAG does not reference
an external payload directory. Payload rows carry a digest over uncompressed logical
bytes and join to slot/target/result relations by that digest. Duplicate bytes are
deduplicated within the relation parts without collapsing their occurrence links.

The canonical relation grains, keys, merge strategies, source identities, and operation
links are defined in the versioned
[representation materialization contract](representation_materialization_contract.md).
That contract replaces the earlier per-target `processing_results` and run-scoped-only
`slot_payloads` draft. In short, the DAG keeps filing identity, target outcomes, physical
slot/type evidence, source-to-current-payload links, per-run operation outcomes, immutable
operation attempts, successful representations, input links, and digest-keyed typed
payloads as separate relations. It writes only changed Parquet parts; relation resolution
and projection joins use the shared DAG engine.

Published payload bytes are held only in the typed Parquet payload relations, not in
SQLite run state, JSON manifests, or worker receipts. Each digest maps through
`payload_index` to exactly one typed payload relation. For a new digest, any
`DocumentRoute.BINARY` source use selects `binary_payloads`; otherwise it selects
`text_payloads`. An existing digest retains its already-pinned storage class if a later
route uses it differently. HTML/markup remains a text source route. The selected payload
relation preserves exact bytes and a valid UTF-8 projection when available; route stays
on source/representation metadata.
`source_payloads` and `representations` join to `payload_sha256`; each distinct
materialization retains its own operation/provenance row, while an identity representation
reuses the source row. Each DAG snapshot has independent Parquet relations for
`binary_payloads` and `text_payloads`; optional join indexes are also Parquet relations
and use the same digest key. The complete bundle response is not copied
into the durable snapshot by default: it remains transient extraction input, while
explicit S9 fixture capture can retain the exact envelope for offline replay. Every
successfully acquired physical-slot body, including an initial slot later replaced by
lazy recovery, is retained in its payload relation. The target-selection relation
records which body S10 processed.

Payload relations use the repository Parquet contract: Zstandard compression and
128,000-row-group sizing, with bounded parts and resource-derived writer memory. The
uncompressed-byte digest and byte size are independent of Parquet's internal
compression. `DocumentRoute.BINARY` from `edgar_sec.domain.document.route` helps choose
the first storage class for a digest; `.html` is never classified as binary media.

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
2. Requires every work-order target and every operation result to have a terminal
   disposition. If a target is `failed`, `ambiguous`, or `required_missing`, or an
   operation is `failed`, publication requires explicit `--allow-errors`; the
   manifest records target and operation counts and `complete_with_errors`. Optional
   `not_filed`, skipped targets, and unsupported/unrequested operations are explicit
   terminal outcomes, not processing failures.
3. Streams metadata rows and selected source/derived payloads into bounded staging
   Parquet writers. Verify exact uncompressed digest/size before accepting each row.
   `payload_index` assigns each digest to one binary/text relation, deduplicating bytes
   without dropping slot, target, operation, or representation joins.
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
acquisition project --target-plan <id> --branch <name> [--max-response-bytes <bytes>]
acquisition project --target-plan <id> --branch <name> --fixture <fixture-id>
acquisition status --run-id <id>
acquisition run --run-id <id> [--retry-failures]
acquisition publish --run-id <id> [--branch <name>] [--allow-errors]
acquisition query --snapshot <id|current> [target/slot filters]
acquisition fixture create|fill|list|replay ...
acquisition distrib export|worker|import ...   # planned; common CLI uses --work-id
```

Project resolves and pins the chosen branch tip, chunk size, acquisition byte ceiling,
and input source mode; `--fixture` pins fixture replay instead of live SEC fallback.
The interactive operator shows Project, Status, combined Run/Process, and Publish.
Run requires explicit network authorization for acquisition, then processes each
acquired target under the same run lock; processing itself is offline.
Publish must target the pinned branch and compare-and-swap the pinned base; a stale tip
requires re-projecting against the new parent.
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
| Legacy fixtures and old snapshot payload layout drove replay and viewer discovery. | S9 fixture SQLite retains explicit source responses for offline evidence; acquisition snapshots publish only planned selected bodies and distinct S10 representations. The viewer does not register the retired dataset; migration of any externally retained artifact is separate. |

Retain bounded worker execution, integrity checks, explicit fixture replay, immutable
publication, and pointer-last safety as general invariants. Do not port legacy
date/name candidate gates, occurrence expansion, selected-index schemas, implicit
delegation, raw/normalized payload ambiguity, or old artifact layouts. The exact
user-confirmed placeholder paths are specified separately in S6.

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
   publisher. Decide migration of any externally retained legacy artifact separately.

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
- PDF extraction, XBRL package execution, taxonomy activation, and old artifact
  migration are outside the snapshot publication implementation and require their
  stated independent evidence/compatibility decisions. The `document_storage` runtime
  is retired; S11 does not restore it.
