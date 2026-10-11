# `edgar_sec/domain/forms/` — Cover, Form, and Exhibit Domain Vocabulary, Contracts, and Evidence Packs

## Purpose

Every table, pattern, and data contract the SEC form normalization engine needs: canonical form aliases, label vocabularies, checkmark token boundaries, statutory checkbox constraints, form-family evidence packs, exhibit coverage ledgers, and assessment profiles. All of it is data; none of it reads or fetches documents.

## Contracts

- **Declarative only**: The checkmark solver and cover boundary detector belong to `engine/forms/`; this subtree owns the data they read.
- **Zero I/O**: All content is data; nothing reads or fetches documents.
- **Layer-1 purity**: Zero internal dependencies on `infra`, `engine`, `pipelines`, or `apps`; only `edgar_sec.foundation` imports.

## Subpackages

- `common/` — Shared cover and exhibit contracts and data models.
- `exhibits/` — Item 601 and Form 20-F coverage ledgers, exhibit authority profiles, and pack registry.
- `families/` — Form family taxonomies (annual/10-K, quarterly/10-Q, current/8-K) with item vocabularies and primary profiles.
- `cover/` — Cover page schemas, checkmark tokens, and boundary detection contracts.

## Deliberate gaps

- **Checkbox schemas are declared twice**: `ANNUAL_CHECKBOX_SCHEMA` and `QUARTERLY_CHECKBOX_SCHEMA` are built independently in `common/schemas.py` and `families/`; import the family module and keep common copies in step.
