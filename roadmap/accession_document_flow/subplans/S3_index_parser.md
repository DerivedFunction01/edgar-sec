# S3 — Pure HTML Index Parser

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S3**.
- Status: pure input/output contract; table-discovery and column-variant rules are
  finalized from the S0 stratified audit.
- Depends on: S0 evidence for parser scenarios and XBRL evidence labeling; the S2
  fixture store for captured page bytes.
- Non-blocking: S1 cohort schema, S2 capture store, S4 broker+pool, S5 snapshot.

## Objective

Parse a raw `-index.html` response into all `Document Format Files` and `Data Files`
rows plus separate bundle metadata. The parser is pure, stateless, and offline: no
network, no SQLite, no profile, no `document_storage`, and no snapshot imports.
Unknown or unsupported page structure is typed as unrecognized rather than returned as a
successful empty result.

## Interface

```text
parse_html_index(html_bytes) -> IndexParseOutcome
```

Inputs:

- `html_bytes`: exact bytes of a cached or live `-index.html` response. No URL or
  filename is required; the caller resolves the accession identity before parsing.

Outputs:

```text
IndexParseOutcome
    status: "parsed" | "unrecognized"
    entries: list[IndexEntry]
    bundle_url: str | None
    bundle_size: int | None
    diagnostics: bounded diagnostics
```

`IndexEntry` fields match the S1/S5 `InventoryEntry` row fields. `diagnostics` is
bounded so a malformed page cannot blow up the result size.

## Parsing rules

- Discover `Document Format Files` and `Data Files` tables independently. A table whose
  header does not match either name is a candidate table; its presence changes
  diagnostics but does not create an entry.
- Emit one entry per body row, keyed by `(table_kind, row_ordinal)`.
- Preserve sequence, type, label, description, filename, href, size, and link presence
  exactly as observed. Missing values are null, never inferred.
- Normalize filename and description text consistently (whitespace normalization, case
  folding) so identical source content produces identical rows across eras.
- Escape or neutralize HTML entities in text fields so the stored value matches the
  rendered text.
- Validate href origin: an `archive_url` is constructed only for same-accession SEC
  archive paths. Any href escaping the accession archive namespace is recorded but not
  promoted to `archive_url`; out-of-tree hrefs are flagged in diagnostics.
- Resolve bundle metadata from the page's advertised envelope URL and size.
- Construct the XBRL ZIP URL only as a documented candidate. Its existence is not
  asserted by the parser; the S0 decision record supplies the availability label for
  target planning.

## Row-identity rules

- Sequence and filename are not keys. A row is identified by `(table_kind, row_ordinal)`
  for merge stability.
- Absent, duplicated, or out-of-order sequences are preserved as observations, not
  repaired.
- A row whose filename or type cannot be read is still emitted with nullable fields,
  because sequence/order can disambiguate it during bundle extraction.

## Error and refusal behavior

- Unrecognized structure (no matching index tables) returns `status: unrecognized` with
  an empty entry list. It never returns a successful empty result.
- Malformed HTML returns a typed `parse_error` diagnostic with bounded detail; it is not
  swallowed into a successful parse.
- Size values that are missing, non-numeric, or negative are null; a bogus size is not
  guessed.
- An absolute or relative href is accepted; only an out-of-tree or scheme-violating
  href is flagged.

## Inputs

- S2-captured response bytes served through read-only replay, or live survey responses
  recorded during S0.
- The audit's table-discovery matrix supplies era-specific header names and column
  positions.

## Tests

Sanitized real-page fixtures from the S0 audit:

- missing sequence,
- duplicated sequence,
- duplicate filename,
- absent link,
- relative and absolute href,
- escaped text,
- missing and invalid size,
- `Data Files` table,
- empty table,
- unknown table,
- unsafe/out-of-tree href,
- malformed HTML,
- unrecognized page structure.

Additional tests:

- identical normalized inputs produce identical entries across eras,
- `parse_html_index` has no network, SQLite, profile, or snapshot dependencies,
- an unrecognized page returns `unrecognized` rather than `parsed` with an empty list,
- diagnostics remain bounded for adversarial input,
- stable entry ordering independent of parser traversal order.

## Acceptance criteria

`parse_html_index()` over raw bytes returns all document/data-file rows and separate
bundle metadata with no network, SQLite, profile, `document_storage`, or snapshot
imports. Unknown or unsupported page structure is typed as unrecognized rather than a
successful empty result. The parser is fully exercised against sanitized real-page
fixtures for every audit case.
