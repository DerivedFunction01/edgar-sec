# `edgar_sec.pipelines.document_inventory.snapshot.projection`

## Purpose

Own pre-fetch plan projection: validation and bounded input-part resolution
for catalog plans, DuckDB staging of cohort and target relations, cohort
relation schemas and fingerprinting, projection run identity and manifest
lifecycle, and the bounded projection of published catalog plans into
transient work orders.

## Contracts

- **Catalog plans are projected before the inventory phase**; normalized
  cohort facts and source edges are retained separately, and only missing
  accession pages enter the work order.
- **Projection inputs are validated against the base snapshot before
  staging**; an incompatible or missing base refuses projection.

## Deliberate gaps

None.
