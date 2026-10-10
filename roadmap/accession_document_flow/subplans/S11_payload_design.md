# S11 — Durable Payload-Store Decision (Design Gate)

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S11**.
- Status: **design gate, not implementation.** No storage code is delivered; a reviewed decision record is the output.
- Depends on: S9 acquisition/fixture cases and S10 processor review cases.
- Precedes: any durable payload-store implementation or `document_storage` cutover.

## Current tracked-code audit (2026-10-08)

- **Status: design gate remains open; no approval or decision record is evidenced.** The representative S9 acquisition cases and S10 processing-review cases required as decision inputs are not implemented, so the candidate comparison and evidence-based approval checklist cannot yet be completed.
- **Evidence:** the command-oriented [S9 acquisition contracts](document_acquisition/cli_inventory.md) and [S10 audit](S10_processing.md) record the missing prerequisite artifacts. The existing [`document_storage` processor](../../../edgar_sec/pipelines/document_storage/processor.py) and persisted snapshot path are legacy behavior, not an S11 decision or replacement-store implementation; [`document_storage_disposition.md`](../document_storage_disposition.md) keeps that package frozen pending the retirement gate.
- **Next step:** complete and review S9/S10 representative fixture cases first; then write the required decision record with evidence, rejected alternatives, migration implications, and explicit approval identity/date. Do not implement or cut over a durable replacement before approval.

## Objective

Choose durable raw-payload and normalized-representation storage only after representative target sources, acquisition routes, and processing outputs have been reviewed. The decision must remain separate from S5's annual metadata snapshot and S6's immutable target plans.

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

## Design questions

The design record must answer all questions with a proposal, evidence, and rejection rationale for credible alternatives:

1. **Raw-payload identity.** Is a fetched envelope keyed by content digest, request URL plus digest, or acquisition event? Distinguish full submission bundles from selected child-document bytes; identical bytes should be deduplicable without losing their target occurrences.
2. **Normalized representation identity.** Which representation and schema versions combine with source digest and processor fingerprint? State whether processor changes create a new immutable representation or replace a prior one.
3. **Occurrence relationships.** How do many target IDs, accessions, `source_origin` values, and CIK source relationships point to one byte-identical payload? Do not reinterpret S5's `source_cik` relation as a verified legal co-filer list.
4. **Source provenance and replay.** Which target-plan manifest, URL, response digest, extraction selector/sequence, selected-body digest, route, and processor identity are required for byte-for-byte replay?
5. **Idempotence and reprocessing.** How are repeated fetches, duplicate content, changed extraction rules, and changed processor fingerprints distinguished and safely retried?
6. **Physical layout.** Compare payload layout independently from S5 annual metadata parts. Address large/binary bodies, normalized text/XML, small-file counts, random reads, and streaming writes.
7. **Retention and deletion.** Define source, selected-body, and normalized-output retention separately. Preserve data referenced by active target plans or published representations; specify safe unreferenced-blob collection.
8. **Inventory/plan linkage.** Keep S5 inventory facts and S6 plans immutable. If a payload occurrence links to an inventory row, record that linkage in the payload/occurrence layer; never add payload locator or digest columns to S5.

## Storage candidates to evaluate

| Candidate | Strengths to measure | Risks to measure |
|---|---|---|
| Content-addressed blob store (CAS) with metadata/occurrence tables | Streams large and binary bodies, deduplicates identical bytes across targets, direct digest lookup, natural immutable body objects. | Requires reference accounting and garbage collection, plus a separate query/index layer; file-count and object-store consistency costs. |
| Annual Parquet with binary payload columns | Columnar metadata scans and alignment with annual query partitions. | Large variable-size blobs amplify rewrites, complicate bounded streaming and point retrieval, and mix analytical rows with opaque binary payloads. S5's annual layout is not sufficient evidence to choose this for bodies. |
| DuckDB columnar storage | Local analytical joins and compact metadata indexing in one engine. | Must prove suitability for large BLOB serving, concurrent readers/writers, atomic updates, remote reads, and blob-level retention before treating it as the canonical payload store. |

Score each candidate against replay fidelity, storage/read amplification, duplicate rate, atomicity, bounded memory, concurrency, query patterns, retention, operations, and migration effort. CAS is a candidate to investigate, not a pre-approved decision; DuckDB may remain a metadata/query engine even if body bytes live elsewhere.

## Candidate relational identity model

The current preferred relational sketch separates physical slot metadata, acquired
bytes, observed type evidence, and target assignment. It is a candidate for the S11
decision record, not an approved durable schema:

| Relation | Candidate key and grain | Candidate contract |
|---|---|---|
| `acquisition_slots` | `(accession, sequence)`; stable `accession_seq_hash` may be its surrogate key. One row per observed physical position. | Store observed document path, source URL, and retrieval mode. Sequence 1 is the physical anchor for the catalog `primaryDocument` link, not a statutory-primary assertion. Index rows or bundle extraction may add other sequence slots. |
| `slot_payloads` | Link from a physical slot to content-addressed bytes. | Store the CAS digest, route, and decoded byte size only for a successfully acquired payload. Transport/extraction failures belong to the append-only attempt ledger, not a payload-link row with `status=failed`. Repeated content may share one CAS object; retain each slot link. Preserve prior payload observations if the same slot later yields changed bytes rather than silently overwriting history. |
| `slot_types` | Sparse source-metadata observations for one slot. | Write no row until index or bundle metadata supplies a type. Keep evidence source/reference (index snapshot/row or SGML bundle child), observed type, and publication/observation time. A local screen result belongs to the target resolution record, not this relation. Multiple metadata sources may disagree; retain provenance and derive the current view deterministically rather than erasing evidence. |
| `target_slot_selections` | Target ID plus resolution/attempt identity. | Link S6 target intent to the physical slot whose body S10 consumed. Preserve the original sequence-1 attempt, any index lookup, and the chosen replacement sequence. This is required because one target may resolve away from its catalog-anchored slot and multiple targets may reuse one slot. |

The simplified sketch's single-row `slot_types` key `(slot, evidence_kind)` is
insufficient for an append-only evidence history across refreshed snapshots or
conflicting observations. The production key must include an evidence identity (for
example snapshot ID/digest plus entry ID, or source-body digest plus document ordinal)
and a deterministic current-evidence rule. Likewise, `slot_payloads` should not encode
failed fetches; the S9 attempt ledger already owns failure outcomes. Exact constraints,
hash serialization, indexes, transaction boundaries, and retention remain open for the
approved S11 design.

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

These relational tables are separate from the current S9 transient run/fixture
contracts and from S5's `accessions`, `entries`, and `accession_sources` relations.
S11 approval is required before durable payload links, CAS bytes, or reconciliation
outputs are published.

## Annual inventory and target-plan invariants

- The S5 snapshot remains annual, immutable, and queryable; no payload part/hash/offset field is introduced there.
- `source_origin="inventory_index" | "catalog_direct"` and the input plan/snapshot references are occurrence provenance, not payload identity.
- A `catalog_direct` occurrence records a catalog-supplied locator, not an index-verified
  statutory type. Cover-boundary or delegation diagnostics do not promote it to an
  inventory fact or authorize a replacement target.
- A target-plan row is intent. It does not become a payload occurrence until acquisition succeeds and the selected bytes have a verified digest.
- A target discovered ad hoc by S9/S10 has no pinned `target_id` and cannot become a
  payload occurrence; publish inventory evidence and a new S6 plan first.
- S9 fixture source bodies are raw SQLite BLOBs retained as bounded review evidence.
  Their schema and cleanup rules do not silently become the production payload store.

## Replacement and migration boundary

The `document_storage` implementation remains frozen during S9–S12 and is scheduled for removal when the replacement is complete. The design must state a cutover plan: behavior parity gates, old-artifact read compatibility or migration, consumer transition, rollback window, and explicit deletion approval. S11 approval alone permits a payload-store implementation; it does not authorize deleting `document_storage` or its artifacts. Decommissioning is a separate post-S12 milestone after the approved payload store is implemented, replacement parity is demonstrated, and consumers/artifacts are migrated.

## Approval checklist

The design is ready for approval only when it:

- Answers all eight questions and compares the three storage candidates using the representative S9/S10 corpus.
- Defines identities for raw response, selected child, normalized representation, target occurrence, and provenance without conflating them.
- Specifies append/update/idempotence, byte verification, streaming bounds, atomic publication, and recovery after interruption.
- Defines retention/reference tracking and safe deletion for raw, selected, normalized, and review-only bodies.
- Leaves S5/S6 schemas unchanged and keeps catalog-direct provenance distinct.
- Includes migration/cutover implications for `document_storage` without mixing its removal into S9–S12.
- Records design version, unresolved risks, rejection rationale, and explicit approval identity/date.

## Gate criteria

Until the design is explicitly approved:

- No durable production payload Parquet, CAS, DuckDB BLOB, or payload linkage is emitted by any stage.
- S5's annual inventory schema and S6 target plans remain metadata/intent only.
- Normalized outputs exist only in bounded worker memory or selected S7 review artifacts; raw bodies remain transient or in the S9 acquisition fixture store.
- No `document_storage` code or artifact is migrated, rewritten, or deleted.

## Deliverable and acceptance

A reviewed design record under `roadmap/accession_document_flow/` containing the proposals, alternatives, evidence matrix, schema/identity choices, retention and migration gates, and explicit approval. The stage completes only after approval and before any durable payload-store implementation begins.
