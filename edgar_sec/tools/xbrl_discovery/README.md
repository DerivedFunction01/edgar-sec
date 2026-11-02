# xbrl_discovery

Layer 6. XBRL linkbase seeding and taxonomy archive construction.

## Purpose

Materialize the XBRL artifacts that evaluation reads: per-cohort linkbase
Parquet tables from SEC filings or fixtures, and per-vintage taxonomy
declaration slices from the official releases.

## Contracts

- **Out-of-repo download cache**: Official releases download into a cache
  outside the repository; only derived Parquet slices land in-tree.
- **One slice per vintage**: Each (taxonomy, version) writes its own slice
  under the taxonomy archive dir.
- **Canonical cohort registry**: Seed filings resolve from the canonical
  cohort file shared with evaluation.

## Deliberate gaps

- **No evaluation**: Scoring, screening, and verification belong to
  `xbrl_eval`.
