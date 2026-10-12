# review_artifacts

## Purpose

This package owns the persisted review-run output produced from captured index pages
and the offline analysis of those outputs. It keeps run-level integrity and table
findings close to the manifest, entry rows, and observation records they consume.

## Contracts

- **Output integrity**: Analysis verifies digests for each parsed output file it reads.
- **No replay or network**: Analysis consumes stored manifests, CSV rows, observations,
  and local form provenance; it never reparses source HTML or fetches a document URL.
- **Acquisition evidence**: URL findings describe observed path shapes and routes, not
  HTTP reachability or authorization to acquire every exhibit.
- **Determinism**: Findings and comparisons use stable run, input, table, and row keys.

## Deliberate gaps

- **Child reachability**: The analyzer does not issue HTTP requests, so it cannot prove
  that a document or bundle URL is live or would return a non-404 response.
- **Source-table verification**: It compares persisted parsed tables across runs; it
  does not reconstruct rows from raw or inert HTML.
