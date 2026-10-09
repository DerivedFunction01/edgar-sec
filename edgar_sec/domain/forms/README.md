# `edgar_sec/domain/forms/` — Cover and Form Domain Vocabulary, Contracts, and Evidence Packs

## Purpose

Every table, pattern, and data contract the SEC form normalization and evaluation engine
needs: canonical form aliases, label vocabularies, checkmark token boundaries, statutory
checkbox constraints, form-family evidence packs, and evaluator decision types. All of it
is data; none of it reads or fetches documents.

## Contracts

- **Declarative only**: The checkmark solver, cover boundary detector, and evaluator execution belong to `engine/forms/`; this subtree owns the data they read.
- **Zero I/O**: All content is data; nothing reads or fetches documents.
- **Layer-1 purity**: Zero internal dependencies on `infra`, `engine`, `pipelines`, or `apps`; only `edgar_sec.foundation` imports.

## Deliberate gaps

- **Checkbox schemas are declared twice**: `ANNUAL_CHECKBOX_SCHEMA` and `QUARTERLY_CHECKBOX_SCHEMA` are built independently in `common/schemas.py` and `families/`; import the family module and keep common copies in step.
