# S7b — Index Parser Fixture Review Bootstrap

## Owner and status

- Cross-cutting S7 slice after the CLI/fixture lifecycle in
  [S7a](S7a_inventory_cli.md).
- Status: review-artifact generation and structural inert previews are implemented;
  semantic keyed parser-run comparison remains incomplete.
- Depends on S7a, S2's fixture reader, and S3's typed parser contract.
- Enables iterative S3 parser review; S0 evidence and S0-selected real fixtures arrive
  in parallel and are required for final parser acceptance.
- Does not depend on S4 production workers, S5 snapshots, S6 target plans, or S12.

Verified implementation evidence: `edgar_sec/pipelines/document_inventory/review_artifacts/`
and `tests/pipelines/document_inventory/review_artifacts/` cover fixture replay, parser
statuses, artifact outputs, worker ordering, and inert rendering. The command is exposed
as `inventory review generate` through the shared review CLI.

## Objective

Make captured index pages and parser outcomes inspectable during parser development.
Semantic parser-run comparison is optional follow-up development tooling, not a
prerequisite for S3. This review loop is not the production inventory build path; it
makes no SEC requests and does not publish snapshot data.

## Commands

```text
inventory review generate --fixture <id> --output <new-directory>
    [--accession <accession> ...] [--limit <n>] [--workers <n>] [--json]

inventory review compare --base <review-run> --new <review-run> [--output <new-directory>]
```

`review generate` selects captured accession/key pairs in deterministic accession
order, obtains exact uncompressed response bytes from the S2 reader, and calls
`engine.index_pages.parser.parse_html_index` with the domain `IndexPageInput` record.
A parser refusal produces an explicit outcome and does not fabricate an empty parsed
page. Source preview and outcome metadata remain reviewable when parsing refuses a page.
Non-parsed outcomes contribute to the command's nonzero exit status.

## Artifacts

```text
{artifacts_root}/document_inventory/review-runs/{review_id}/
  manifest.jsonl
  cases/{accession}/source.inert.html
  cases/{accession}/observations.json
  cases/{accession}/entries.csv
```

Each manifest row pins fixture ID, accession, request URL, response SHA-256, parser
fingerprint, status, and digests for files that were written. `observations.json`
records the typed parser status, bundle/XBRL candidate metadata where available, and
bounded diagnostics (`items`, `suppressed_count`). `entries.csv` uses the S3
`InventoryEntry` fields in `(table_kind, row_ordinal)` order. A refused or failed parse
has no fabricated `entries.csv`; the failure is recorded in
the observation and manifest. The output directory must be new or empty, and each
case file is written atomically.

`source.inert.html` is rebuilt with the existing selectolax-backed
`engine.document.html.tree.parse_html`; no new HTML dependency is needed. Preserve
table headers, rows, cells, and visible filing-page text with an allowlist; discard
active-content and embedded-resource subtrees, and emit no source attributes. Rendered
text is escaped; links are plain text. Add only renderer-generated document structure
and a restrictive CSP.
Regex tag/attribute stripping is not an acceptable sanitizer: malformed markup and
attribute syntax make it an unreliable security boundary. Review operations read only
the local fixture store and make zero HTTP requests.

## Execution and resource boundaries

- The S2 reader validates fixture/schema provenance and returns exact decompressed
  response bytes; it does not return SQLite's stored zstd frame to the parser.
  Whole-database digest behavior is optional and decided in S7a; every selected body
  is checked against its response digest.
- Review workers use the `spawn` process context and `derive_resources().workers`.
  The coordinator reads one fixture body at a time and keeps at most the resolved
  worker count submitted/uncollected. Each worker handles one accession, writes only
  its isolated review-case directory, and returns a small manifest record.
- The final `manifest.jsonl` is written in selection order, not process completion
  order. One failed case does not erase successful case artifacts; the command
  returns nonzero if any selected case failed.
- Drop response bytes after each case and call `reclaim()` at bounded worker and
  coordinator batches. No full fixture body collection is retained in memory.

## Comparison status

The available shared `review compare` command compares generated review directories.
Its inventory adapter uses set-based CSV row comparison and JSON observation diffs. It
does not enforce identical fixture/page inputs or report parser-entry changes keyed by
`(accession, table_kind, row_ordinal)`. Bundle metadata, status, diagnostic, and
field-level changes are not yet presented as the semantic diff described by the target
contract below. Parser fingerprints identify implementation semantics; S3 owns and
increments `PARSER_FINGERPRINT` when they change.

## Tests

- Verified in `tests/pipelines/document_inventory/review_artifacts/`: builder tests
  cover manifest/artifact output, replay failure without entries, empty selection,
  occupied output refusal, deterministic case paths, and parallel manifest ordering.
  Sanitizer tests cover tables, event attributes, a JavaScript URL, external resources,
  active-content subtrees, malformed markup, and a generated CSP.
- The implementation reads the local fixture store and has no network client dependency;
  there is no dedicated transport-spy test. Broader hostile-markup combinations,
  byte-identical reruns, keyed semantic comparison, and S0-selected real-page tests
  remain unverified.
- Tests do not inject a fake parser. The committed successful parser case is the
  standard-layout fixture; S0-selected source pages are still required for era coverage.

## Acceptance

Users can select an S2 fixture and run `inventory review generate` to inspect its inert source
and current parser status/results. As S3 evolves, identical fixture bytes produce
reviewable, parser-fingerprinted results. A run-diff command is optional; full S7
target-plan, snapshot, and acquisition review surfaces remain downstream of their own
artifacts.
