# `edgar_sec/apps/runner` — Layer 5: high-throughput pipeline orchestrator

## Purpose

This package provides a unified coordinator that chains the repository's verified
pipeline primitives (`filing_catalog`, `document_planning`, and `document_acquisition`)
into automated, end-to-end execution runs without manual plan-passing ceremony.

It delivers relational DataFrame results; SEC rate pacing is owned by the transport layer (`infra.sec_http`), not by this package.

## Contracts

- **Pipeline delegation**: Uses public pipeline coordinators rather than duplicating batch processing.
- **Transport lifecycle**: The SEC transport is wrapped lazily for the run and closed on exit; this package owns no socket daemon or broker.
- **Resource bounds**: Worker counts pass through as `requested_workers`; the acquisition pipeline's resource derivation bounds them against cgroup limits.
- **Relational output**: Emits `FilingsResult` instances holding pointers to DuckDB-readable target relations.
- **Roles resolve or refuse**: Every requested role maps into the run — `primary`, generic `exhibit`/`exhibits`, generic `linkbase`/`linkbases`, and concrete `EX-` types — or the run refuses with a coded `ProfileResolutionError`. The published plan stays primary-only; non-primary targets ride the run as ephemeral acquisition intents.

## Deliberate gaps

- **No custom ETL transformations**: Engine parsers and pipeline processors own all document transforms.
- **No independent storage layout**: Artifacts are staged strictly through owning pipeline path resolvers.
