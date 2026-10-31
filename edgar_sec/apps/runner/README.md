# `edgar_sec/apps/runner` — Layer 5: high-throughput pipeline orchestrator

## Purpose

This package provides a unified coordinator that chains the repository's verified
pipeline primitives (`filing_catalog`, `document_planning`, and `document_acquisition`)
into automated, end-to-end execution runs without manual plan-passing ceremony.

It manages the inter-process SEC rate-limiting broker lifecycle, invokes collision-reconciled
target matching, and delivers relational DataFrame results.

## Contracts

- **Pipeline delegation**: Uses public pipeline coordinators rather than duplicating batch processing.
- **Broker management**: Manages socket daemon broker lifecycle and cleans up transient sockets on exit.
- **Resource bounds**: Clamps worker allocations to cgroup limits via resource derivation.
- **Relational output**: Emits `FilingsResult` instances holding pointers to DuckDB-readable target relations.

## Deliberate gaps

- **No custom ETL transformations**: Engine parsers and pipeline processors own all document transforms.
- **No independent storage layout**: Artifacts are staged strictly through owning pipeline path resolvers.
