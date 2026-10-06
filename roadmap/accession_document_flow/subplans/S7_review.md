# S7 — Index and Target-Plan Review Surfaces

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S7**.
- Status: review-API design; offline, source-first comparison built from fixtures and
  published artifacts.
- Depends on: S2 index fixture store, S3 parser, S5 snapshot, S6 target plans.
- Non-blocking: S9/S10 acquisition/processing review, S12 CLI.

## Objective

Provide offline `review-artifacts`, `review`, and snapshot `inspect` APIs for
source-page parse output, target plans, and saved manifests. Add CLI routes only for
these review capabilities and basic snapshot/plan lookup; do not build the interactive
wizard here.

## Sanitized inert source preview

`source.inert.html` generates a safe, inspectable preview of the raw index page:

- **Markup sanitization**: Previews are generated from sanitized, rebuilt markup.
  Scripts (`<script>`), inline/remote styles (`<style>`, `<link rel="stylesheet">`),
  external resources (`<img>`, `<video>`, `<audio>`), event handlers (`onload`,
  `onclick`), frames (`<iframe>`, `<frame>`), and form elements are stripped.
- **Inert links**: Hyperlinks are **not** rendered with active or pseudo-URI anchors
  (do not use `href="javascript:void(0)"`). Link anchors are converted to plain
  inert text or have `href` stripped entirely.
- **Defense in depth**: Previews include `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; sandbox;">`.
  Sanitization is the primary guarantee; CSP is defense in depth.
- **Zero HTTP**: All review operations read solely from local fixture SQLite stores or
  published Parquet snapshots; network calls are strictly banned.

## Review surfaces and diff structures

- **Index review artifacts**: Replays an index-page fixture through a chosen parser
  version. Emits `source.inert.html`, parsed accession metadata (`observations.json`),
  and ordered rows (`entries.csv`). Pinned in `manifest.jsonl`.
- **Index review comparison**: Compares two parser runs across identical fixture
  responses, keyed strictly by `(accession, table_kind, row_ordinal)`. It reports:
  - Field-level changes: `document_type`, `sequence`, `description`, `filename`,
    `href`, `byte_size`.
  - Bundle metadata changes: `bundle_url`, `bundle_size`.
  - Status changes: `parsed`, `unrecognized`, or parse errors.
  - Stage diagnostics and warning codes.
- **Target-plan review**: Compares two plan runs (or profile changes) across
  identical pinned source artifacts. Diffing is keyed by
  `(accession, request_id, source_origin, inventory_entry_id)`; catalog-direct rows
  have null `inventory_entry_id` and remain distinct by `source_origin`.
  It reports outcome status transitions (`not_filed` $\leftrightarrow$ `matched`,
  `unresolved` $\leftrightarrow$ `ambiguous`) separately from profile selector edits
  and source-origin/source-artifact changes. `status_reason` changes remain visible
  even when the status itself is unchanged.
- **Snapshot inspect**: Reads a pinned published snapshot only, reporting its annual
  partition layout, part manifest, and counts grouped by form and filing year.

## Review output shapes

```text
{artifacts_root}/document_inventory/review-runs/{review_id}/
  manifest.jsonl
  cases/{accession}/source.inert.html
  cases/{accession}/observations.json
  cases/{accession}/entries.csv
{artifacts_root}/document_planning/review-runs/{review_id}/
  manifest.jsonl
  target-plan-diff.json
{artifacts_root}/document_processing/review-runs/{review_id}/
  manifest.jsonl
  cases/{target_id}/source.inert.html
  cases/{target_id}/normalized.txt
  cases/{target_id}/processing.json
```

Each `manifest.jsonl` row pins fixture ID, source URL/digest, accession or target ID,
source snapshot/catalog/plan IDs when applicable, parser/processor fingerprint, result
status, and digests for generated review files.

## Command contracts

- All review outputs refuse a non-empty destination directory.
- One bad case is reported and does not erase successful case outputs.
- The command returns nonzero when any selected case failed.
- Review runs are reproducible from fixture ID plus selected accession/target IDs and
  parser/processor identity.

## CLI routes

Initial CLI routes are review-capability oriented:

```text
inventory review-artifacts --fixture <id> --output <dir>
inventory review --base <dir> --new <dir>
inventory inspect --snapshot <id|current> [--accession <accession>]
```

## Tests

- Deterministic manifests: identical fixture + parser version reproduces byte-identical
  review artifacts.
- Safe source rendering: all links are inert text; script and style tags are stripped;
  CSP header is embedded; zero `javascript:` URIs exist.
- Network instrumentation confirms exactly zero HTTP requests during all review runs.
- Parser diffs: detects row additions, deletions, field modifications, and diagnostic
  shifts across parser versions for the same fixture response.
- Target-plan diffs: keyed by `(accession, request_id, source_origin, entry_id)`;
  catalog-direct and inventory-index rows remain separate, and outcome transitions
  are isolated from profile/source changes.
- Empty selection refusal: empty case selection returns a typed error.
- One-case failure behavior: a single failed case does not erase successful sibling cases.
- Non-empty output refusal: pre-existing destination directories are rejected.
- Snapshot inspect against a pinned snapshot returns layout and counts without fetch.
- Zero writes to the future payload store.

## Acceptance criteria

Offline `review-artifacts`, `review`, and snapshot `inspect` APIs serve source-page
parse output, inventory- or catalog-direct target plans, and saved manifests. Source HTML is actively sanitized into
inert previews without active anchors or remote loads. Parser and plan diffs isolate
identity-keyed field and outcome transitions. CLI routes are strictly review-focused.
