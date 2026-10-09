# `edgar_sec/engine/document/html` — DOM access, cleaning, break survival, projection

## Purpose

Reduce filing markup to text that later stages can reason about line by line,
without losing a table byte or inventing a page boundary that was not there.

## Contracts

- **Table bytes survive every pass.** Tables are masked before unescaping entities,
  so a table containing `&amp;` is returned unchanged.
- **Cleaning preserves what downstream stages key on.** Symbolic fonts
  (`Wingdings`/`Webdings`/`Symbol`), `colspan`/`rowspan`, borders,
  `align`/`text-align`/`width`, `display:none`, and page-break declarations are
  never stripped.
- **Cleaner pass order is important**: inline XBRL first (its tags carry their
  own style attributes, so glyph normalization must see them after the wrapper is
  gone), Unicode whitespace sanitization last.
- **Glyph expansion is scoped to symbolic-font text nodes.** Tags, attributes,
  comments, scripts, and styles are untouched, and a nested font declaration
  replaces the inherited one.
- **Break markup inside a table is never converted.** A decorative `<hr>` row rule
  would become a sentinel the ASCII table renderer then wraps as cell text.
- **`<br><br>` inside a `<p>` collapses to a space**; between block tags it
  survives as a paragraph break. A repeated marker is preserved rather than
  merged — two breaks in a row are evidence of a blank page.
- **No barrel re-exports.** `__init__.py` is a docstring; consumers import leaf
  modules.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Production consumers

- `edgar_sec/engine/document/unpacking/representation.py` —
  `clean_html_for_parsing` and `strip_non_displaying_blocks`.
- `edgar_sec/engine/document/html/breaks.py` → `normalize_html_document`.
- `edgar_sec/engine/document/page_markers/policy.py` — `render_html_to_break_text`,
  reached from `engine/forms/normalize.py` on the HTML branch.
- `edgar_sec/engine/tables/ascii_html/` — `parse_html` / `FastHtmlNode`.
- `edgar_sec/pipelines/document_storage/review_artifacts.py` — `parse_html`.

`decompose_html_structures` and `insert_page_sentinels` are called only from
inside this package; their composed entry point is `render_html_to_break_text`.

## Deliberate gaps

- **`decompose_html_structures` is not a whole-document entry point.** It
  projects markup for tagged `<TABLE>` blocks and returns a plain `str`; table
  conversion, false-table cleanup, hybrid `<pre>` handling, and geometry
  composition are `normalize_html_document`'s job. Callers that need the
  per-table `TableGeometry` mapping must use `normalize_html_document`, whose
  `NormalizedHtmlText` carries it.
- **Break sentinels reach a text frame only through `render_html_to_break_text`.**
  Whether a `<PAGE>` marker becomes a token or a removal is decided by
  `page_markers.policy`, not here.
- **`<noscript>` is not purged.** `strip_non_displaying_blocks` removes exactly
  `<head>`, `<script>`, and `<style>`; `<noscript>` fallback text is document content a
  reader sees when scripting is off, so it stays in the frame.
- **This package has no opinion on page markers.** It preserves *where* a break
  was; deciding whether that break is page furniture is `page_markers`.
