# `edgar_sec.engine.index_pages`

## Purpose

Transform an SEC filing index-page response into typed inventory outcomes without fetching or persisting data.

## Contracts

- **Parsing consumes explicit bytes and domain records**: Uses shared HTML-tree engine; no network or artifact access.
- **Unknown/malformed structure yields typed refusal/failure**: Never fabricates an empty success.
- **Engine imports are restricted to `infra`, `domain`, `foundation`**: No pipeline or frozen `document_storage` imports.

## Deliberate gaps

- **Final era/table rules**: Await empirical audit (S0); current behavior covered by standard filing-page fixture.
