# S11 — Durable Payload-Store Decision (Design Gate)

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S11**.
- Status: **design gate, not implementation.** No code is delivered; a separate
  reviewed design is the artifact.
- Depends on: S9 acquisition results and S10 processing review cases.
- Precedes: any durable payload-store implementation.

## Objective

Decide the durable fetched-payload storage model from reviewed acquisition and
processing evidence, then require explicit approval before any implementation code is
written. This stage is a decision record, not a pipeline.

## Inputs

Representative observed target plans and acquisition/processing review cases covering:

- direct HTML documents,
- legacy SGML bundle extraction,
- XML and iXBRL documents,
- data files,
- binary documents,
- failures and missing bodies,
- repeated identical bytes across accessions.

Each input case is keyed by source URL and body digest from the S9 acquisition
fixture, with the processor fingerprint and output digest from S10.

## Design questions

The design document must answer each of the following with a concrete proposal and a
counter-proposal rejection rationale:

1. **Raw-payload identity.** Key by source URL + body digest, by accession + filename,
   or by content hash? How is a re-fetched identical body identified?
2. **Normalized representation identity.** Is a normalized document keyed by
   representation kind + source identity, with versioning across processor updates?
3. **Occurrence and co-filer relationships.** How does one payload relate to multiple
   source CIKs and to merged filings?
4. **Source provenance.** What is retained to make a byte-for-byte replay possible?
5. **Idempotence and reprocessing.** How are stale normalized representations
   invalidated or reprocessed when the processor changes?
6. **Part and partition boundaries.** Raw, normalized, and index linkage across
   storage layers.
7. **Retention and deletion.** What governs purge, and how does it interact with
   target-plan references?
8. **Inventory-to-payload linkage.** How do inventory `entries` reference stored
   payloads, if at all.

**Explicit prohibition:** do not add `payload_part`, `payload_hash`, or
`payload_offset` to the inventory schema. The inventory is a pre-fetch metadata index;
payload linkage belongs to the payload store, not to it.

## Gate criteria

Implementation of durable payload storage requires explicit approval of this design
from the architectural review. Until approved:

- No payload Parquet, blob CAS, or payload linkage is emitted by any stage.
- The inventory schema stays unchanged.
- Review artifacts record output digests only; bodies remain transient or in the
  acquisition fixture.

## Deliverable

A reviewed design document under `roadmap/accession_document_flow/` containing:

- the inventory payload relationship model,
- the storage layout,
- the identity and provenance scheme,
- the idempotence and retention policy,
- approval checklist,
- and the migration implications for `document_storage` if it is ever replaced.

## Acceptance criteria

The stage completes only when the design document is written and explicitly approved
before any implementation code lands. No durable payload artifacts are emitted; the
inventory schema is unchanged.
