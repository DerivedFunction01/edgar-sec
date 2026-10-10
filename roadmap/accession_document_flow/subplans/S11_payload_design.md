# S11 — Durable Payload Snapshot Publication

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S11**.
- Status: **design documented; implementation gate remains open.** The acquisition
  lifecycle plan now fixes the proposed Parquet/DAG model, relations, worker/processing
  boundaries, transient lifetime, and publication protocol. No storage code is
  delivered until representative S9/S10 evidence is reviewed and this design is
  approved.
- Depends on: S9 acquisition/fixture cases and S10 processor review cases.
- Precedes: any durable payload-store implementation or `document_storage` cutover.

## Current tracked-code audit (2026-10-08)

- **Status:** a concrete Parquet/DAG replacement design is now documented in
  [the acquisition lifecycle plan](document_acquisition/lifecycle.md). It supersedes
  the former open-ended storage alternatives; representative acquisition/processing
  cases and explicit approval are still outstanding.
- **Evidence:** the command-oriented [S9 acquisition contracts](document_acquisition/cli_inventory.md),
  [S10 audit](S10_processing.md), and the existing
  [`document_storage` processor](../../../edgar_sec/pipelines/document_storage/processor.py)
  show which behaviors are separated or replaced. Legacy artifacts remain frozen
  pending the independent retirement gate in
  [`document_storage_disposition.md`](../document_storage_disposition.md).
- **Next step:** implement the M7 fixture-driven S9/S10 gate, review its representative
  cases against the lifecycle plan's schemas and failure/retention contracts, then
  record approval before enabling durable publication.

## Objective

Publish raw selected bodies and derived processing representations through the
acquisition-owned immutable Parquet/DAG design in
[the lifecycle plan](document_acquisition/lifecycle.md), after its representative
source and processing cases pass review. The acquisition snapshot remains separate
from S5's annual metadata snapshot and S6's immutable target plans.

## Inputs

Representative captured cases cover:

- Inventory-index direct URLs and legacy bundle-sequence targets.
- Catalog-direct targets, with their separate `source_origin` and plan provenance.
- ASCII `.txt` passthrough, HTML/iXBRL visible-text, standalone XML, data files, and
  binary/PDF routes.
- Missing targets, oversized responses, malformed bundles, extraction ambiguity, and processing failures.
- Repeated identical source bytes across accessions, target plans, and CIK source relationships.
- Reprocessing the same source bytes under a changed processor fingerprint.

Each case pins the S6 target plan and source artifact, S9 response/selected-body digests, and S10 processor fingerprint/output digest. SQLite-BLOB fixture bodies from [S9 fixture capture/replay](document_acquisition/fixtures/index.md) are evidence only, not a presumption about the durable-store design.

The representation corpus distinguishes HTML's raw source from its derived text;
ASCII `.txt` passthrough and validated XML may alias their source bytes; PDF remains
raw-only until an extractor is approved. Identity-equal representations must not be
counted as independently transformed payloads merely because they have different
roles in the schema.

## Design contract to validate

The lifecycle plan resolves these questions as follows; S11 review validates the
proposal against captured evidence and records residual risk rather than reopening
unbounded design alternatives:

1. **Raw-payload identity.** Payload rows are keyed by exact uncompressed byte SHA-256; slot/target/run relations preserve independent physical and request occurrences. Durable default is the selected child, not the redundant full submission envelope.
2. **Derived identity.** A derived payload row is keyed by the exact output digest; its `processing_results` row records source digest, representation, processor fingerprint, output schema, and size. Processor changes create new immutable evidence and never overwrite prior output.
3. **Relationships.** `target_results`, `acquisition_slots`, `slot_payloads`, `slot_types`, `target_slot_selections`, and `acquisition_attempts` preserve target intent, physical slot, byte identity, and source provenance independently. S5 `source_cik` remains outside the acquisition target relation.
4. **Provenance and replay.** Published run rows pin the S6 plan identity and preserve exact source/selected digests, retrieval/extraction evidence, slot selection, route, and S10 fingerprint. Explicit S9 fixtures retain complete source responses when exact envelope replay is required.
5. **Idempotence.** One run/schema/parent identity publishes at most once; digest-keyed payload rows deduplicate identical bytes. Changed extraction or processor versions produce distinct result evidence and do not rewrite prior snapshots.
6. **Layout.** Metadata, exact selected source bytes, and derived content are stored in DAG Parquet parts. `DocumentRoute.BINARY` rows are separate from text-route rows; HTML is text/markup, not binary media. S5 annual inventory parts do not store body payloads.
7. **Retention.** Selected raw bodies and distinct derived representations are retained while reachable from published snapshots. Transient source/selected/processed files are retained until Parquet publication or explicit discard. DAG compaction traces branch/tag/pin reachability.
8. **Inventory/plan linkage.** Snapshot rows pin S5/S6 source IDs and digests and copy only required target provenance. S5/S6 schemas remain immutable; index-only reconciliation writes acquisition-owned metadata without acquiring bodies or processing them.

## Storage choice and rejected alternatives

| Candidate | Decision |
|---|---|---|
| Typed binary/text Parquet payload relations in the acquisition DAG | **Selected proposal.** Binary-media payloads and non-binary text/markup/XML payloads use separate Parquet relations joined to slot/target metadata by digest. DAG publication is pointer-last and retention follows reachable parts. |
| External CAS files plus Parquet metadata | Rejected: introduces a second durable storage format and requires independent compression, atomicity, and garbage-collection semantics. |
| DuckDB BLOB payload tables | Rejected as canonical payload format: durable bodies must remain Parquet; DuckDB may serve bounded metadata queries, not replace Parquet payload parts. |

Validate this choice against replay fidelity, Parquet write/read amplification,
duplicate bytes, atomicity, bounded memory, concurrency, query patterns, retention,
operations, and migration effort. An evidence failure reopens the choice with a
recorded amendment; the implementation default is no longer unspecified.

## Candidate relational identity model

The lifecycle plan defines this durable relation model, separating physical slot
metadata, acquired bytes, observed type evidence, and target assignment:

| Relation | Candidate key and grain | Candidate contract |
|---|---|---|
| `acquisition_slots` | `(accession, sequence, observation_id)`; the physical identity remains `(accession, sequence)`. | Store the observed document path, source URL, retrieval mode, and evidence identity. Multiple observations for a physical slot are preserved. Sequence 1 is the physical anchor for the catalog `primaryDocument` link, not a statutory-primary assertion. |
| `slot_payloads` | Link from a physical slot to a Parquet payload row. | Store the payload digest, route, and uncompressed byte size only for a successfully acquired payload. Transport/extraction failures belong to the append-only attempt ledger, not a payload-link row with `status=failed`. Repeated content shares a digest-keyed row; retain each slot link. Preserve prior payload observations if the same slot later yields changed bytes rather than silently overwriting history. |
| `slot_types` | Sparse source-metadata observations for one slot. | Write no row until index or bundle metadata supplies a type. Keep evidence source/reference (index snapshot/row or SGML bundle child), observed type, and publication/observation time. A local screen result belongs to the target resolution record, not this relation. Multiple metadata sources may disagree; retain provenance and derive the current view deterministically rather than erasing evidence. |
| `target_slot_selections` | Target ID plus resolution/attempt identity. | Link S6 target intent to the physical slot whose body S10 consumed. Preserve the original sequence-1 attempt, any index lookup, and the chosen replacement sequence. This is required because one target may resolve away from its catalog-anchored slot and multiple targets may reuse one slot. |

The `slot_types` key includes an evidence identity (for example snapshot ID/digest
plus entry ID, or source-body digest plus document ordinal) so refreshed or conflicting
observations are not overwritten. Current views resolve only from retained evidence
under an explicit deterministic rule; raw evidence remains available for audit.
`slot_payloads` never encodes failed fetches; the S9 attempt ledger owns failure
outcomes. Exact Arrow/SQL constraints are owned by the lifecycle plan's relation
schemas and are versioned before implementation.

### Selector and enrichment behavior

- `submitted_primary` fetches the catalog's sequence-1 link and performs no type
  evaluation or lazy index request. Its bytes can enter the slot payload relation,
  while `slot_types` remains empty unless independent index/SGML evidence is observed.
- `exact_form_with_lazy_index` performs the local ASCII `<TYPE>` or HTML cover
  suspicion screen after sequence 1 is acquired. An ASCII `<TYPE>` mismatch or
  unverifiable/missing type, or a cover result that cannot verify the filing form,
  triggers bounded index discovery. A positive HTML
  cover result avoids the extra lookup but is not itself a type fact. A locally
  accepted screen, including a matching SGML header, is recorded in the target
  resolution and does not by itself create a `slot_types` row. The exact form is
  selected only by an observed index row whose `document_type` matches the filing
  form; no sequence/filename guess is permitted.
- A lazy lookup may retain the sequence-1 payload and acquire a second slot for the
  actual primary. Its target-slot assignment names only the selected body for S10.
  An already-acquired slot payload can be reused with zero document-body requests.
- A later S5 snapshot can enrich slot locator/type metadata without re-fetching or
  re-processing payloads. S5 remains an immutable inventory snapshot; a downstream
  reconciliation reads its pinned facts and adds/upserts acquisition-side metadata.
  An index fetch is still a network request, but this mode performs no document-payload
  fetch or S10 work. S9/S5 must not write one another's owned artifacts.

These durable relations are separate from the S9 transient run/fixture contracts and
from S5's `accessions`, `entries`, and `accession_sources` relations. S11 approval is
required before durable payload links, Parquet body columns, or reconciliation
outputs are published; their proposed schema and publication behavior are specified,
not deferred.

## Annual inventory and target-plan invariants

- The S5 snapshot remains annual, immutable, and queryable; no payload part/hash/offset field is introduced there.
- `source_origin="inventory_index" | "catalog_direct"` and the input plan/snapshot references are occurrence provenance, not payload identity.
- A `catalog_direct` occurrence records a catalog-supplied locator, not an index-verified
  statutory type. Cover-boundary or delegation diagnostics do not promote it to an
  inventory fact or authorize a replacement target.
- A target-plan row is intent. It does not become a payload occurrence until acquisition succeeds and the selected bytes have a verified digest.
- A target discovered ad hoc by S9/S10 has no pinned `target_id` and cannot become a
  payload occurrence; publish inventory evidence and a new S6 plan first.
- S9 fixtures retain Zstandard-compressed exact-response SQLite BLOBs as bounded replay
  evidence. Their schema and cleanup rules do not become the production Parquet store.

## Replacement and migration boundary

The `document_storage` implementation remains frozen during S9–S12 and is scheduled for removal when the replacement is complete. The design must state a cutover plan: behavior parity gates, old-artifact read compatibility or migration, consumer transition, rollback window, and explicit deletion approval. S11 approval alone permits a payload-store implementation; it does not authorize deleting `document_storage` or its artifacts. Decommissioning is a separate post-S12 milestone after the approved payload store is implemented, replacement parity is demonstrated, and consumers/artifacts are migrated.

## Approval checklist

The design is ready for approval only when it:

- Validates all eight decisions against representative S9/S10 cases and records any
  evidence-driven amendment to the Parquet/DAG proposal.
- Defines identities for raw response, selected child, normalized representation, target occurrence, and provenance without conflating them.
- Specifies append/update/idempotence, byte verification, streaming bounds, atomic publication, and recovery after interruption.
- Defines retention/reference tracking and safe deletion for raw, selected, normalized, and review-only bodies.
- Leaves S5/S6 schemas unchanged and keeps catalog-direct provenance distinct.
- Includes migration/cutover implications for `document_storage` without mixing its removal into S9–S12.
- Records design version, unresolved risks, rejection rationale, and explicit approval identity/date.

## Gate criteria

Until the documented design is explicitly approved:

- No durable production payload Parquet part or payload linkage is emitted by any stage.
- S5's annual inventory schema and S6 target plans remain metadata/intent only.
- Normalized outputs exist only in bounded worker memory or selected S7 review artifacts; raw bodies remain transient or in the S9 acquisition fixture store.
- No `document_storage` code or artifact is migrated, rewritten, or deleted.

## Deliverable and acceptance

A review record under `roadmap/accession_document_flow/` containing the lifecycle-plan
version, representative evidence matrix, any schema/identity amendments, residual
risks, retention and migration gates, and explicit approval. The design is now present
in `document_acquisition/lifecycle.md`; S11 completes only after review approval and
before any durable payload-store implementation begins.
