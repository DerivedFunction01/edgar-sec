# execution

Layer 4 acquisition subpackage for run execution.

## Purpose

This package executes validated work orders: it orchestrates one resumable acquisition run under its run lock, acquires each eligible target through the retrieval mode planning pinned, runs the run-scoped ephemeral-intent pass, and hands acquired targets to processing under the same lock. It owns the per-target acquisition machinery — attempt and resolution evidence builders, index-entry selection, and the bundle-scan variant — that the run orchestrator composes.

## Contracts

- **Pinned retrieval**: Execution follows the source and sequence planning selected; it does not compare advertised sizes, group targets into a shared bundle fetch, or fall back from an ordinary failed direct request to the accession bundle.
- **Bounded staging**: Responses stage under the run's transient staging root, subject to the finite response limit resolved through the shared settings registry.
- **Evidence per attempt**: Every fetch records an attempt and, where selection occurred, a target-slot resolution in the run's state store; ephemeral-intent resolutions live only in that store and die with the run.
- **Same-lock processing**: Acquired targets are processed under the same run lock before the run report is composed.

## Deliberate gaps

- **No run validation**: Persisted runs are validated before transport is initialized by the package root's `run_validation`; this package executes already-validated work orders.
- **No publication**: Snapshot publication and review remain separate packages; execution ends at the run report.
