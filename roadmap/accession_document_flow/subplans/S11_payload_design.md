# S11 — Durable Payload-Store Decision (Design Gate)

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S11**.
- Status: **design gate, not implementation.** No storage code is delivered; a reviewed decision record is the output.
- Depends on: S9 acquisition/fixture cases and S10 processor review cases.
- Precedes: any durable payload-store implementation or `document_storage` cutover.

## Current tracked-code audit (2026-10-08)

- **Status: design gate remains open; no approval or decision record is evidenced.** The representative S9 acquisition cases and S10 processing-review cases required as decision inputs are not implemented, so the candidate comparison and evidence-based approval checklist cannot yet be completed.
- **Evidence:** the S9a–S9d and S10 audits in their subplans record the missing prerequisite artifacts. The existing [`document_storage` processor](../../../edgar_sec/pipelines/document_storage/processor.py) and persisted snapshot path are legacy behavior, not an S11 decision or replacement-store implementation; [`document_storage_disposition.md`](../document_storage_disposition.md) keeps that package frozen pending the retirement gate.
- **Next step:** complete and review S9/S10 representative fixture cases first; then write the required decision record with evidence, rejected alternatives, migration implications, and explicit approval identity/date. Do not implement or cut over a durable replacement before approval.

## Objective

Choose durable raw-payload and normalized-representation storage only after representative target sources, acquisition routes, and processing outputs have been reviewed. The decision must remain separate from S5's annual metadata snapshot and S6's immutable target plans.

## Inputs

Representative captured cases cover:

- Inventory-index direct URLs and legacy bundle-sequence targets.
- Catalog-direct targets, with their separate `source_origin` and plan provenance.
- HTML, iXBRL visible-text, standalone XML, data files, and binary/PDF routes.
- Missing targets, oversized responses, malformed bundles, extraction ambiguity, and processing failures.
- Repeated identical source bytes across accessions, target plans, and CIK source relationships.
- Reprocessing the same source bytes under a changed processor fingerprint.

Each case pins the S6 target plan and source artifact, S9 response/selected-body digests, and S10 processor fingerprint/output digest. Fixture CAS bodies in S9d are evidence only, not a presumption about the durable-store design.

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

## Annual inventory and target-plan invariants

- The S5 snapshot remains annual, immutable, and queryable; no payload part/hash/offset field is introduced there.
- `source_origin="inventory_index" | "catalog_direct"` and the input plan/snapshot references are occurrence provenance, not payload identity.
- A target-plan row is intent. It does not become a payload occurrence until acquisition succeeds and the selected bytes have a verified digest.
- S9 fixture body files remain bounded review evidence. Their directory layout, compression, and cleanup rules do not silently become the production payload store.

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
- Normalized outputs exist only in bounded worker memory or selected S7 review artifacts; raw bodies remain transient or in S9d's acquisition fixture store.
- No `document_storage` code or artifact is migrated, rewritten, or deleted.

## Deliverable and acceptance

A reviewed design record under `roadmap/accession_document_flow/` containing the proposals, alternatives, evidence matrix, schema/identity choices, retention and migration gates, and explicit approval. The stage completes only after approval and before any durable payload-store implementation begins.
