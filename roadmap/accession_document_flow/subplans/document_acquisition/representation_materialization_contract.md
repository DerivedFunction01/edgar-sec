# Representation materialization and reuse contract

**Status: proposal for agreement; not implementation authorization.** This contract
defines the missing identity and relation layer between S6 operation requests, S9
source acquisition/reuse, and a future acquisition snapshot. It does not enable S10
processing, M7, M9, or S11 publication.

## Decision

Add an acquisition-owned representation relation that maps a logical output to a
content-addressed payload. Do not put accession or sequence on the payload row and do
not use the S6 `target_id` as the cross-plan key. Keep accession/sequence-to-source
mapping, source-to-payload mapping, and operation-to-representation mapping separate.
The existing accession/CIK relation remains the filing identity owner; observed
statutory type remains separate evidence about an accession/sequence slot.

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

## Stable identities

- `source_asset_id` identifies one logical source locator independently of plan and content:
  SHA-256 of canonical JSON `[accession, source_key]`. `source_key` is the validated
  canonical SEC archive-relative path, or a typed exact-sequence key for a bundle child.
  A source digest is deliberately not part of this identity so a
  changed body is recorded as a new payload observation for the same source.
- `logical_document_id` identifies the requested document independently of its plan:
  SHA-256 of canonical JSON `[accession, request_id, source_asset_id]`. Ambiguous candidate
  sources therefore remain distinct. A target in a later plan joins to the same
  logical document only when accession, derived role/type request, and resolved source
  identity all match.
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
source of truth.

| Relation | Grain / key | Sketch of columns and role |
|---|---|---|
| `accession_ciks` | `(inventory_snapshot_id, accession)` | `cik`; minimal filing-identity evidence reconciled from the pinned S5 snapshot. Kept separate from document/slot payloads. |
| `source_assets` | `source_asset_id` | Canonical source key and effective path/locator facts. Stable across plans; no response bytes, sequence, or operation status. |
| `acquisition_slots` | `(accession, sequence, observation_id)` | Existing physical-slot observation plus `source_asset_id`; maps observed sequence/accession to the stable source. No statutory type inference. |
| `slot_types` | `type_evidence_id` | Existing sourced type evidence keyed to accession/sequence observation, with evidence/parser identity. Never copied onto the payload row. |
| `logical_documents` | `logical_document_id` | Stable `(accession, request_id, source_asset_id)` identity plus target role/type provenance. Different candidate source assets remain distinct. |
| `target_results` | `(run_id, target_id)` | Existing plan/run outcome plus `logical_document_id`; preserves the plan-specific target binding without using it for reuse. |
| `target_slot_selections` | `(run_id, target_id, resolution_id)` | Existing target-to-slot selection and evidence links. Joins through `acquisition_slots`; it does not overwrite a source identity. |
| `acquisition_attempts` | `(run_id, attempt_id)` | Existing append-only request/attempt outcomes, including source asset and successful selected payload digest where applicable. Failures remain here, not in payload relations. |
| `source_payloads` | `(source_asset_id, payload_sha256)` | Successful retained raw source bytes, route and uncompressed size; index for cross-plan source reuse. This replaces the run-scoped-only reuse role of `slot_payloads`; slot views join through `source_asset_id`. |
| `operation_requests` | `(run_id, target_id, operation)` | One final disposition for each operation in the closed vocabulary, including unrequested ones: `not_requested`, `unsupported`, `available`, or `failed`. Requested rows carry the S6 `operation_id`, capability/handler versions, latest attempt ID, and successful `representation_id` when available. `pending` is transient run state and is not publishable. |
| `operation_attempts` | `(run_id, operation_attempt_id)` | Append-only operation tries: `target_id`, operation, attempt ordinal, ordered input fingerprint, handler/capability/options versions, `available`/`failed`, error code, and optional representation link. |
| `representations` | `representation_id` | Successful output identity: logical document, operation, output kind, capability/handler/options versions, output payload digest and size. No bytes or accession/sequence copy. `raw` is an identity representation pointing at the source payload digest. |
| `representation_inputs` | `(representation_id, input_ordinal)` | Input source asset and exact input payload digest, plus semantic input role. Keeps the bytes used by a transform reproducible and auditable. |
| `binary_payloads` | `payload_sha256` | Existing Parquet byte relation for binary-route payloads. |
| `text_payloads` | `payload_sha256` | Existing Parquet byte relation for non-binary payloads, including raw markup, text, and XML. |

`slot_payloads` can be projected by joining `acquisition_slots` to `source_payloads`;
it need not duplicate the same accession/sequence/payload mapping in another base
relation. `accession_ciks` and `slot_types` remain independent joins. The payload
relations contain only digest-keyed bytes and byte metadata.

`operation_requests` is run-scoped because “not requested” describes one plan/run, not
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
  `operation_requests`, `representations`, and `representation_inputs`; payload reads
  join by digest only when requested.

This resolves the raw-then-render case without a special combined table: Plan A adds a
raw representation and `render_to_txt=not_requested`; Plan B adds a new run's request,
reuses the parent-lineage `source_payloads` row, and adds a distinct render
representation. Both representations remain reachable in the projected snapshot.

The exact Arrow schemas, `RelationSpec` merge strategies, and compatibility version
are to be frozen with S6/S11 owners before implementation. The DAG engine already
supports immutable parts and relational resolution; this proposal adds domain schemas,
not a new snapshot mechanism.

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
- `available` requires a verified representation row and payload whose digest and
  size match the produced bytes. It records the operation and handler version even
  when its digest aliases another payload.
- An existing raw payload is reusable only when the new plan resolves to the same
  stable `source_asset_id`, the prior successful body is retained and readable in the
  selected DAG lineage, and its payload digest/size verify. Reuse does not reselect a
  target or promote diagnostic evidence into a locator.
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
