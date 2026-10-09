# `edgar_sec.engine.index_pages`

## Purpose

Transform an SEC filing index-page response into typed inventory outcomes without fetching or persisting data.

## Contracts

- Parsing consumes explicit bytes and domain records, uses the shared HTML-tree engine, and performs no network or artifact access.
- Unknown or malformed structure yields typed refusal/failure outcomes, never a fabricated empty success.
- Engine imports are restricted to `infra`, `domain`, and `foundation`; this package imports no pipeline or frozen `document_storage` modules.

## Deliberate gaps

- Final era/table rules await the empirical audit tracked by S0; current behavior is covered by the standard filing-page fixture.
