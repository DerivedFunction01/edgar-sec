# `edgar_sec/engine/forms/cover/toc` — table-of-contents span detection

Finds the exclusive source span containing a filing's table of contents, so the
boundary stage knows where the cover ends and the body begins.

## Purpose

The finder runs a strict ladder and returns the first method that reaches its row
minimum. That ordering is the package's central guarantee: a heading-led TOC is
never reported as the weaker density or aligned-row forms, because a caller
reading `method` can trust that `heading_rows` means a heading *and* rows were
both found.

## Contracts

- **Methods, strongest first**: `heading_rows`, `weak_heading_rows`, `tagged_table_merged`, `tagged_table`, `density_score`, `anachronism_late_item`, `aligned_rows`.
- **Only `aligned_rows` sets `approximate=True`**: Every other method is a positive identification.
- **A `TABLE OF CONTENTS` heading whose rows start far later is mid-document navigation text, not a TOC start, and is not returned**
- **A table boundary is claimed only when the last TOC row still sits inside an open `<TABLE>` region whose close falls inside the search limit**.
- **A page-break-split continuation table is merged and reported as `tagged_table_merged`**: with `"merged across page break"` in the boundary evidence. A single table never carries that text.
- **End refinement runs in two passes**: aligned residue past the claimed boundary is absorbed first, then a PART/ITEM sequence reset truncates the span. The reset evidence row names the line where the span was cut.
- **`start_offset` and `end_offset` are character offsets into the same string `start_line` and `end_line` index into**.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **The row predicates are not declared here**: `is_toc_row`, `looks_like_toc_row`, `looks_like_toc_tabular`, `RE_TOC_ITEM_ROW`, `RE_TOC_LEADER`, `RE_PAGE_SUFFIX`, `RE_PART_REFERENCE`, and `RE_ITEM_REFERENCE` live in `edgar_sec.engine.tables.toc.patterns` and are imported. Table classification refuses the same rows, and the two sides must agree on what a TOC row is; a second copy would drift.
- **`derived_taxonomy` is duck-typed, not modelled**: A caller may pass a plain dict of vocabulary strings, or one carrying a `matcher` object that answers `has_any()` and `find_matches()`. Neither shape is validated here, and a dict missing a key silently falls back to the default vocabulary.
- **`INDEX` and `REFERENCE(S)` are treated as TOC headings only when rows corroborate them**: A real index in the back of a filing is therefore reported as a TOC. The cover stage only scans the front of the document, so this does not arise there, but a caller scanning later text will get a false positive.
- **No body-boundary side**: The span's `end_line` is where the TOC stops, not where the body starts; body resolution is a separate stage.
