# Parser review artifacts

Builds offline, parser-fingerprinted evidence from captured index-page fixtures.

| Module | Responsibility |
|---|---|
| `builder.py` | Bounded case selection, parsing, output, and manifest commit |
| `sanitizer.py` | Structural inert HTML reconstruction |
| `paths.py` | Review-run and response-case output layout |
| `models.py` | Review run summary records |

## Contracts

Each captured response is digest-checked and processed independently. Source previews
are rebuilt without source attributes or active/resource subtrees. Failed pages retain
status and diagnostics and never receive an `entries.csv`. Case output is atomically
renamed, and manifest rows are committed in deterministic selection order.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

`inventory review-artifacts` is wired by the document-inventory operator.

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
| Logical Artifact | Resolution Seam |
| :--- | :--- |
| `broker_socket_path(...)` | Method |
| `catalog_file` | Property |
| `fixture_database_path(...)` | Method |
| `fixture_manifest_path(...)` | Method |
| `fixture_root(...)` | Method |
| `fixtures_root` | Property |
| `index_fixture_paths(...)` | Method |
| `projection_staging_root` | Property |
| `publication_lock_path` | Property |
| `review_manifest_path(...)` | Method |
| `review_run_root(...)` | Method |
| `review_runs_root` | Property |
| `runtime_root` | Property |
| `snapshot_part_path(...)` | Method |
| `snapshot_root(...)` | Method |
| `snapshots_root` | Property |
| `transient_root` | Property |
<!-- AUTOGEN:PATHS:END -->

## Deliberate gaps

Parser-run diffing and review of snapshot/acquisition outputs remain downstream work.
