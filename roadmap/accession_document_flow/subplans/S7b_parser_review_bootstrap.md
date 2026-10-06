# S7b — Index Parser Fixture Review Bootstrap

## Owner and status

- Cross-cutting S7 slice after the CLI/fixture lifecycle in
  [S7a](S7a_inventory_cli.md).
- Depends on S7a, S2's fixture reader, and S3's typed parser contract.
- Enables iterative S3 parser review; S0 evidence and S0-selected real fixtures arrive
  in parallel and are required for final parser acceptance.
- Does not depend on S4 production workers, S5 snapshots, S6 target plans, or S12.

## Objective

Make captured index pages and parser outcomes inspectable during parser development.
Parser-run comparison is optional follow-up development tooling, not a prerequisite for S3. This
review loop is not the production inventory build path; it makes no SEC requests and
does not publish snapshot data.

## Commands

```text
inventory review-artifacts --fixture <id> --output <new-directory>
    [--accession <accession> ...] [--limit <n>] [--workers <n>] [--json]

inventory review --base <review-run> --new <review-run> [--output <new-directory>]  # optional
```

`review-artifacts` selects captured accession/key pairs in deterministic accession
order, obtains exact uncompressed response bytes from the S2 reader, and calls
`engine.index_pages.parser.parse_html_index` with the domain `IndexPageInput` record.
A parser refusal produces an explicit failure
case status; it must not fabricate an empty parsed page. Source preview and failure
metadata remain reviewable when a parser refuses a page. The command exposes parser iterations against the same pinned fixture bytes. An
optional `review` command may compare those runs offline after artifact shape stabilizes.

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

## Comparison

Parser-run comparison pins identical fixture/accession/response-digest inputs and
reports row additions/deletions/field changes keyed by
`(accession, table_kind, row_ordinal)`, bundle metadata changes, parse-status changes,
and diagnostic changes. Parser fingerprints identify the implementation semantics;
S3 owns and increments `PARSER_FINGERPRINT` when they change. Comparison output is
deterministically ordered and contains no source HTML.

## Tests

- A refused page creates source previews and an explicit failure status, never
  successful empty entries.
- Replay passes exact uncompressed bytes and matching response digest into the parser
  input; a fixture database is validated once per run.
- Offline-only execution is verified by a transport spy that rejects HTTP.
- Preview generation parses HTML structurally and rebuilds only allowlisted markup;
  it does not sanitize with regex or preserve any source attribute.
- Hostile/malformed markup cases (script/style bodies, event attributes, encoded or
  mixed-case URL schemes, `srcdoc`, SVG/MathML, frames, forms, and embedded resources)
  produce no active element, source attribute, or network load in the preview; the
  renderer-generated CSP is present.
- Artifact manifests pin fixture/page/parser identities and hash written files;
  manifest order is stable across worker completion orders.
- One failed case preserves sibling artifacts and makes the command return nonzero.
- If the optional diff route is implemented, it detects entry, bundle, status, and
  diagnostics changes for equal pinned source pages.
- Empty selections and non-empty output directories are refused.
- Tests do not inject a fake parser. Artifact serialization may be tested with directly
  constructed typed outcomes; successful real-page parser tests are added with S0's
  selected fixtures when S3 parsing is implemented.

## Acceptance

Users can select an S2 fixture and run `review-artifacts` to inspect its inert source
and current parser status/results. As S3 evolves, identical fixture bytes produce
reviewable, parser-fingerprinted results. A run-diff command is optional; full S7
target-plan, snapshot, and acquisition review surfaces remain downstream of their own
artifacts.
