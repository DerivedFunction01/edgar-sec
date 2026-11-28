# xbrl_discovery

Layer 6. XBRL linkbase seeding and taxonomy archive construction.

## Purpose

Materialize the XBRL artifacts that evaluation reads: per-cohort linkbase
Parquet tables from SEC filings or fixtures, per-vintage taxonomy
declaration slices from the official releases, and regenerated discovery
corpus bundles from the tracked accession lists (`accession_lists/`).

## Contracts

- **Out-of-repo download cache**: Official releases download into a cache
  outside the repository; only derived Parquet slices land in-tree.
- **One slice per vintage**: Each (taxonomy, version) writes its own slice
  under the taxonomy archive dir.
- **Canonical cohort registry**: Seed filings resolve from the canonical
  cohort file shared with evaluation.
- **Corpus regeneration writes out-of-repo only**: `regenerate_corpus`
  rebuilds each corpus's per-filing bundles (facts, arcs, declarations,
  namespaces, normalized text, fixture source registry) from its tracked
  accession list into an untracked corpus root; an in-repo output root is
  refused. `verification_trace.json` is not regenerated — it is an authored
  grounded-verification fixture, not a derived bundle member.

## Deliberate gaps

- **No evaluation**: Scoring, screening, and verification belong to
  `xbrl_eval`.
