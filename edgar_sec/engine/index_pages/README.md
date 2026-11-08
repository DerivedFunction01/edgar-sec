# `edgar_sec.engine.index_pages`

## Purpose

Transform an SEC filing index response — the HTML index page or the directory `index.json` listing — into typed inventory outcomes without fetching or persisting data. The same package parses the EDGAR full/daily index files (`.idx`) into streamed filing rows for catalog reconciliation.

## Contracts

- **Parsing consumes explicit bytes and domain records**: Uses shared HTML-tree engine; no network or artifact access.
- **Unknown/malformed structure yields typed refusal/failure**: Never fabricates an empty success.
- **Both vehicles return the same outcome types**: The JSON listing carries names and sizes only; sequence, type, and description stay absent on its entries rather than inferred.
- **Engine imports are restricted to `infra`, `domain`, `foundation`**: No pipeline or frozen `document_storage` imports.
- **Index files stream line-by-line**: An `.idx` payload is parsed as an iterator of rows, never loaded as a document; one row model covers the master/xbrl pipe layout and the company/form/crawler fixed-width layouts, whose column widths vary by era and are therefore anchored on the CIK/date/filename tail, not absolute offsets.
- **Malformed index rows are outcomes, not raises**: A data line that cannot be read yields a malformed-row record with its line number and reason; the good rows around it are unaffected.

## Deliberate gaps

- **Final era/table rules**: Await empirical audit; current behavior covered by standard filing-page fixture.
- **JSON entries do not distinguish data files**: The listing has no table structure, so every JSON-sourced entry is a document-format row, and the listing's modified times have no field in the entry model.
- **No XML/JSON index-data variants**: The full/daily indexes serve no `.xml`/`.json` row variants (those names are directory listings, parsed as inventory, not as index rows), so the `.idx` layouts are the only row encodings.
