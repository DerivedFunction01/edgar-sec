# S7 — Index and Target-Plan Review Surfaces

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S7**.
- Frontloaded fixture CLI: [S7a](S7a_inventory_cli.md). Parser review loop:
  [S7b](S7b_parser_review_bootstrap.md).
- Status: staged review design. S7a creates/fills fixtures; S7b builds parser review
  artifacts to inspect the existing S3 parser pass and later iterations; later review
  surfaces follow their source artifacts.
- S7a depends on S1/S2 and `filing_catalog` plan loading. S7b depends on S7a, S2, and
  the S3 type contract. Later S7 surfaces depend on S5/S6 and (for processing review)
  S9/S10.
- S7b supplies iterative review for S3; the initial parser pass can run against the
  committed standard-layout fixture. S0 remains independent and gates final coverage.
- S7c is target-plan comparison and snapshot inspection after S5/S6. S7d is
  acquisition/processing review after S9/S10.

## Objective

Provide offline review and inspect APIs in dependency-sized slices. **S7a** provides
the fixture CLI lifecycle. **S7b** builds `inventory review-artifacts` from those
fixtures and parser outputs so S3 can iterate through pinned pages. A parser-run
`inventory review` diff is optional after artifact runs exist. Later S7
surfaces compare target plans, inspect S5 snapshots, and review acquisition/processing
artifacts. Do not build the interactive wizard here.

## Sanitized inert source preview

`source.inert.html` generates a safe, inspectable preview of the raw index page:

- **Structural sanitizer**: Parse with the existing selectolax-backed
  `engine.document.html.tree.parse_html`, then rebuild with an allowlist that preserves
  table headers, rows, cells, and visible filing-page text. Drop active-content and
  embedded-resource subtrees, unwrap other unknown tags, and emit no source attributes.
  Escape all text nodes.
  Do not use regex stripping: it is not a safe HTML parser for malformed or adversarial
  source markup.
- **Inert links**: Source anchors are rendered as plain text; source URLs and all other
  source attributes are omitted. Only renderer-generated markup is emitted.
- **Defense in depth**: Previews include a renderer-generated CSP with `default-src
  'none'`, `object-src 'none'`, `base-uri 'none'`, `form-action 'none'`, and
  `sandbox`. Sanitization is the primary guarantee; CSP is defense in depth.
- **Zero HTTP**: All review operations read solely from local fixture SQLite stores or
  published Parquet snapshots; network calls are strictly banned.

## Review surfaces and diff structures

- **S7b — index review artifacts**: Replays an index-page fixture through a chosen parser
  version. Emits `source.inert.html`, parsed accession metadata (`observations.json`),
  bounded diagnostics, and ordered rows (`entries.csv`). Pinned in `manifest.jsonl`.
- **Optional S7b — index review comparison**: Compares two parser runs across identical fixture
  responses, keyed strictly by `(accession, table_kind, row_ordinal)`. It reports:
  - Field-level changes: `document_type`, `sequence`, `description`, `filename`,
    `href`, `byte_size`.
  - Bundle/candidate metadata changes: `bundle_url`, `bundle_size`,
    `xbrl_candidate_url`.
  - Status changes: `parsed`, `unrecognized`, or parse errors.
  - Stage diagnostics and warning codes.
- **S7c — target-plan review**: Compares two plan runs (or profile changes) across
  identical pinned source artifacts. Diffing is keyed by
  `(accession, request_id, source_origin, inventory_entry_id)`; catalog-direct rows
  have null `inventory_entry_id` and remain distinct by `source_origin`.
  It reports outcome status transitions (`not_filed` $\leftrightarrow$ `matched`,
  `unresolved` $\leftrightarrow$ `ambiguous`) separately from profile selector edits
  and source-origin/source-artifact changes. `status_reason` changes remain visible
  even when the status itself is unchanged.
- **S7c — snapshot inspect**: Reads a pinned published snapshot only, reporting its annual
  partition layout, part manifest, and counts grouped by form and filing year.

- **S7d — acquisition/processing review**: Renders selected S9/S10 cases and compares
  processing outcomes against pinned fixture and processor fingerprints. It does not
  affect S7b's parser-development dependency.

S7b reviews the implemented `engine.index_pages.parser.parse_html_index` against pinned
fixture bytes: it emits the inert source preview and records typed parser outcomes
without inventing entries. Parser iteration remains owned by S3.

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

S7a fixture routes are available first. S7b review routes consume the S3 type contract
and pinned fixture pages; later S7 routes are added only after their pinned artifacts
exist:

```text
inventory fixture create --fixture <id> --catalog-plan <id>
inventory fixture fill --fixture <id> --catalog-plan <id>
inventory fixture list
inventory review-artifacts --fixture <id> --output <dir>
inventory review --base <dir> --new <dir>  # optional
inventory inspect --snapshot <id|current> [--accession <accession>]
```

## Tests

S7a tests fixture create/fill/list and plan-independent replay. S7b tests stub-status,
fixture-byte replay, artifact, and sanitizer contracts independently of S5/S6. Parser
diff tests are optional. The tests below for plan comparison and snapshot
inspection remain blocked on those artifacts.

- Deterministic manifests: identical fixture + parser version reproduces byte-identical
  review artifacts.
- Safe source rendering: hostile and malformed markup cannot preserve active tags,
  source attributes, or URL-bearing elements; text is escaped, and the generated CSP is
  present. Tests cover event handlers, obfuscated URL schemes, `srcdoc`, SVG/MathML,
  raw-text elements, and external-resource tags.
- Network instrumentation confirms exactly zero HTTP requests during all review runs.
- If implemented, parser diffs detect row additions, deletions, field modifications,
  and diagnostic shifts across parser versions for the same fixture response.
- Target-plan diffs: keyed by `(accession, request_id, source_origin, entry_id)`;
  catalog-direct and inventory-index rows remain separate, and outcome transitions
  are isolated from profile/source changes.
- Empty selection refusal: empty case selection returns a typed error.
- One-case failure behavior: a single failed case does not erase successful sibling cases.
- Non-empty output refusal: pre-existing destination directories are rejected.
- Snapshot inspect against a pinned snapshot returns layout and counts without fetch.
- Zero writes to the future payload store.

## Acceptance criteria

S7a fixture create/fill/list works without the originating catalog plan. S7b
`review-artifacts` serves source-page parse output from pinned fixtures; optional
`review` compares parser runs, and later `inspect`/plan review follow their artifacts.
Source HTML is structurally parsed and rebuilt as inert previews without source
attributes, active anchors, or remote loads; sanitizer tests cover hostile markup.
