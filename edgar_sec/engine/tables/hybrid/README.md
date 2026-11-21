# `edgar_sec/engine/tables/hybrid` — `<pre>` payload masking for mixed filings

## Purpose

Transition-era filings embed financial tables inside `<pre>` blocks in three shapes:

- **SGML tables** — literal `<TABLE><CAPTION>…<S> <C>…` markup carried as text.
- **Fixed-width monospace text** — a dashed rule over aligned columns.
- **Real HTML tables** — `<table><tr><td>` that happens to sit inside a `<pre>`.

A DOM cannot represent the first two faithfully: literal SGML tags are either parsed as elements or
escaped on serialization, and a monospace block's column alignment depends on whitespace a DOM will
collapse. So this package is a text boundary, not a DOM pass.

## Contracts

- **A `<pre>` payload survives byte for byte**: `normalize_hybrid_pre_text` replaces each payload with a private token, the caller runs ordinary HTML table normalization over the result, and `restore_hybrid_pre_text` puts the payload back unchanged.
- **Restoration is verified, not assumed**: A token that cannot be found raises `ValueError` rather than returning a document with a whole financial table silently missing.
- **A real HTML table inside `<pre>` is rendered**: The one payload shape a DOM *can* represent is converted to canonical ASCII before masking, so the caller's ordinary table pass does not have to reach inside a `<pre>`.
- **Classification never parses the payload as HTML**: A `<pre>` body containing SGML tags must not be interpreted; the shape is decided from the raw source text.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- Nested or unbalanced `<pre>` markup is not recovered.
- No filesystem, no network, no CLI.
