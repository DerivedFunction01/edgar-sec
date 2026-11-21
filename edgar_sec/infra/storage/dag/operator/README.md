# `edgar_sec/infra/storage/dag/operator` — the operator surface

The human-facing surface of the snapshot DAG: the command-line entry, the
SQL console, the interactive menu, and the integrity doctor.

## Purpose

Binds the store core at the parent root (catalog, manifest, paths, spec,
tags) and the working engine in `working/` into the commands an operator
runs: `cli` carries the subcommand surface (branch, checkout, doctor, gc,
log, publish, status, tag), `console` the snapshot SQL console, `menu` the
interactive target/action menu, `operator` the menu entry point, and
`doctor` the graph integrity audit.

## Contracts

- **Surface only**: no storage mechanics live here — commands read and
  mutate snapshots exclusively through the store core and the working
  engine, never by reaching into catalog or manifest files directly.
- **Console containment**: saved queries and exports stay outside the
  snapshot repository; the console's SQL guard admits read-only snapshot
  queries only.

## Deliberate gaps

- **No daemon or scheduler mode**: the menu and console are session
  surfaces; automation binds the CLI or the engine modules directly.
