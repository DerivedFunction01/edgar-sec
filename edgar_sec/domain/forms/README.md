# `edgar_sec/domain/forms/` — Cover, Form, and Exhibit Domain Vocabulary, Contracts, and Evidence Packs

## Purpose

Every table, pattern, and data contract the SEC form normalization engine needs: canonical form aliases, label vocabularies, checkmark token boundaries, statutory checkbox constraints, form-family evidence packs, exhibit coverage ledgers, and assessment profiles. All of it is data; none of it reads or fetches documents.

## Contracts

- **Declarative only**: The checkmark solver and cover boundary detector belong to `engine/forms/`; this subtree owns the data they read.
- **Zero I/O**: All content is data; nothing reads or fetches documents.
- **Layer-1 purity**: Zero internal dependencies on `infra`, `engine`, `pipelines`, or `apps`; imports are `edgar_sec.foundation`, this subtree, and other `edgar_sec.domain` packages only.

## Subpackages

- `common/` — Shared cover and exhibit contracts and data models.
- `exhibits/` — Exhibit coverage ledgers, authority profiles, and pack registry.
- `families/` — Form family taxonomies, item vocabularies, and primary profiles.
