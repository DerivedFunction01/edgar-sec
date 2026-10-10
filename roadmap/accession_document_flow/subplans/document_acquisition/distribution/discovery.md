# `acquisition distrib list` and `commands`

## Purpose and status

Discover worker bundles and render copyable distributed-execution commands. These
commands are design-only for S9; the shared infrastructure supports analogous
pipeline operations.

## `list` contract

- Scan only the acquisition distribution root or an explicit root override.
- Report validated bundle identity, worker, run, assignment size, and state; malformed
  bundles are visible as invalid and are never offered for execution or import.
- Listing performs no network requests and changes no run or bundle state.

## `commands` contract

- Resolve a validated run, partition its pending work using the shared distribution
  contract, and render export, worker, and import commands for the resulting bundles.
- Shell-quote every ID/path value and show coordinator and worker steps in execution
  order. Rendering commands performs no export, SEC request, or import.
- Make the selected run explicit in the rendered commands. Never choose an
  undisclosed plan or run based on directory ordering.

## Acceptance

Listing is read-only. Rendered commands are safe to copy as shell arguments and refer
only to the selected run and generated bundle destinations.
