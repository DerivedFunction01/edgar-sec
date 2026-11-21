# form144

Domain definitions, evidence packs, and processing profile declarations for SEC Form 144 (Notice of Proposed Sale of Securities).

## Purpose

Defines strongly typed immutable schemas for reporting sellers, issuers, proposed broker transactions, acquisition histories (Table I), prior three-month sales (Table II), and conformed signatures.

Encapsulates lexical evidence packs used by the document acquisition and table parsing engine to classify Form 144 document sections.

## Contracts

- **Immutability**: All model dataclasses use frozen slots to prevent accidental in-place mutation.
- **Source fidelity**: Fields not present in source documents remain null/None rather than populated with placeholder strings.
- **Acyclic layering**: Domain models have zero dependencies on engine or infra modules.

## Deliberate gaps

- **Paper filing anomaly OCR**: Paper filings submitted prior to electronic submission mandates are processed via text/HTML table extractors; direct raster image OCR is deferred.
