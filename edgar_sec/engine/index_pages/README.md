# `edgar_sec.engine.index_pages`

## Purpose

Transform an SEC filing index response — the HTML index page or the directory `index.json` listing — into typed inventory outcomes without fetching or persisting data.

## Contracts

- **Parsing consumes explicit bytes and domain records**: Uses shared HTML-tree engine; no network or artifact access.
- **Unknown/malformed structure yields typed refusal/failure**: Never fabricates an empty success.
- **Both vehicles return the same outcome types**: The JSON listing carries names and sizes only; sequence, type, and description stay absent on its entries rather than inferred.
- **Engine imports are restricted to `infra`, `domain`, `foundation`**: No pipeline or frozen `document_storage` imports.

## Deliberate gaps

- **Final era/table rules**: Await empirical audit; current behavior covered by standard filing-page fixture.
- **JSON entries do not distinguish data files**: The listing has no table structure, so every JSON-sourced entry is a document-format row, and the listing's modified times have no field in the entry model.
