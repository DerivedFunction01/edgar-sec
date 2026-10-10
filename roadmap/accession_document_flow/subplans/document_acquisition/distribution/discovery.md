# `acquisition distrib list` and `commands`

## Purpose and status

The common distribution CLI and console are implemented for metadata sync and
inventory. Their adapters discover pipeline-owned work and expose opaque work IDs;
the acquisition adapter and its `list`/`commands` integration remain in planning.

## `list` contract

- Scan only the acquisition distribution root or an explicit root override. The
  common console's work picker is adapter-owned; inventory offers only valid existing
  runs and does not project catalog plans while resolving a work ID.
- Report validated bundle identity, worker, work ID, assignment size, and state; malformed
  bundles are visible as invalid and are never offered for execution or import.
- Listing performs no network requests and changes no run or bundle state.

## `commands` contract

- The common command accepts an opaque `--work-id`; adapters resolve that ID to
  pipeline-owned work and determine its chunks. Acquisition will resolve a validated
  S9 run and render export, worker, and import commands after its adapter is
  implemented.
- Shell-quote every ID/path value and show coordinator and worker steps in execution
  order. Rendering commands performs no export, SEC request, or import.
- Make the selected run explicit in the rendered commands. Never choose an
  undisclosed plan or run based on directory ordering.

## Acceptance

Listing is read-only. The console retains its selected work ID for the session;
rendered commands use the common `--work-id` option and refer only to that selected
work and generated bundle destinations. No cross-host SEC rate coordination or check
is provided by the common distribution layer.
