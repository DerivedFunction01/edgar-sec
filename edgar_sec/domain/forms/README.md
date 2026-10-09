# `edgar_sec/domain/forms/` — Cover and Form Domain Vocabulary, Contracts, and Evidence Packs

## Purpose

Every table, pattern, and data contract the SEC form normalization and evaluation engine
needs: canonical form aliases, label vocabularies, checkmark token boundaries, statutory
checkbox constraints, form-family evidence packs, and evaluator decision types. All of it
is data; none of it reads or fetches documents.

## Contracts

- **Declarative only.** The checkmark solver, the cover boundary detector, and
  evaluator execution are `engine/forms/`'s; this subtree owns the data they read.
- **Layer-1 purity:** zero internal dependencies on `infra`, `engine`, `pipelines`, or
  `apps`, and no third-party imports beyond `edgar_sec.foundation`.

## Deliberate gaps

- **The checkbox schemas are declared twice.** `ANNUAL_CHECKBOX_SCHEMA` and
  `QUARTERLY_CHECKBOX_SCHEMA` are each built independently in `common/schemas.py` and
  in `families/{annual,quarterly}/checkmarks.py`. The two copies compare equal today,
  nothing pins them to each other, and the copies `engine/forms/cover/` imports are
  the family ones — so import the family module and keep the `common/` copies in step.
