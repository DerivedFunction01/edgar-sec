# `engine.tables.hybrid` — `<pre>` payload masking for mixed filings

## Purpose

Transition-era filings embed financial tables inside `<pre>` blocks in three shapes:

- **SGML tables** — literal `<TABLE><CAPTION>…<S> <C>…` markup carried as text.
- **Fixed-width monospace text** — a dashed rule over aligned columns.
- **Real HTML tables** — `<table><tr><td>` that happens to sit inside a `<pre>`.

A DOM cannot represent the first two faithfully: literal SGML tags are either parsed as elements or
escaped on serialization, and a monospace block's column alignment depends on whitespace a DOM will
collapse. So this package is a text boundary, not a DOM pass.

## Module → responsibility

| Module | Responsibility |
|---|---|
| `masker.py` | `PreBlockKind` (the four payload shapes), `HybridPreText` (masked text plus the payload map), `normalize_hybrid_pre_text`, `restore_hybrid_pre_text`. |

## Contracts

- **A `<pre>` payload survives byte for byte.** `normalize_hybrid_pre_text` replaces each payload with
  a private token, the caller runs ordinary HTML table normalization over the result, and
  `restore_hybrid_pre_text` puts the payload back unchanged.
- **Restoration is verified, not assumed.** A token that cannot be found raises `ValueError` rather
  than returning a document with a whole financial table silently missing.
- **A real HTML table inside `<pre>` is rendered.** The one payload shape a DOM *can* represent is
  converted to canonical ASCII before masking, so the caller's ordinary table pass does not have to
  reach inside a `<pre>`.
- **Classification never parses the payload as HTML.** A `<pre>` body containing SGML tags must not
  be interpreted; the shape is decided from the raw source text by `_classify_pre_source`.
  `_looks_like_monospace_text` stays private, as does the classifier.

## Public surface

```python
from edgar_sec.engine.tables.hybrid.masker import (
    HybridPreText,
    PreBlockKind,
    normalize_hybrid_pre_text,
    restore_hybrid_pre_text,
)
```

`normalize_hybrid_pre_text(text) -> HybridPreText`;
`restore_hybrid_pre_text(text, protected: dict[str, str]) -> str`.

## Command surface

None. Library; the stage that drives it lives in `engine/document/html/normalizer.py`.

## Mirrored tests

`tests/engine/tables/hybrid/test_masker.py` (20 tests). The round-trip cases are the point of the
package: an SGML table, a monospace block, an HTML table inside `<pre>`, and a mixed document all
have to come back with their content intact and their `<pre>` tags gone.

## Deliberate gaps

- **Token collision is defended, not impossible.** Masking disambiguates a token that already occurs
  in the document by appending underscores, and restoration raises `ValueError` if a token cannot be
  found. That is why the contract above reads "verified" rather than "guaranteed lossless": a document
  crafted to defeat the nonce can still lose a payload, loudly. The same hazard and the same
  mitigation exist for the `__SEC_RENDERED_TABLE_{n}__` tokens in `ascii_html/converter.py`.
- **No `<pre>` nesting or unbalanced-tag recovery.** `_PRE_BLOCK_RE` matches a non-greedy
  `<pre …>…</pre>` pair; an unclosed `<pre>` is not masked.
- **No geometry is retained for a monospace payload.** Only the HTML_TABLE shape is converted; the
  SGML and monospace shapes are round-tripped verbatim with no `TableGeometry`.