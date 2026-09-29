# `edgar_sec/engine/document` — SGML unpacking, HTML normalization, page-furniture masking

Turns a raw EDGAR payload into normalized plain text: unpacks the SGML submission envelope
into discrete sub-documents, strips HTML transport and presentation noise before parsing,
flattens the remaining markup into text while leaving tagged tables byte-for-byte intact,
detects and removes page furniture, and provides the signature-region and whitespace
primitives every later stage leans on.

It does not decide where the cover page ends or where the body begins — that boundary belongs
to `edgar_sec/engine/forms/cover/`. It does not reflow prose (that is
`edgar_sec/engine/reflow/`) and it does not resolve or tag tables (that is
`edgar_sec/engine/tables/`).

## Purpose

Every SEC filing arrives in one of two hostile shapes: a `.txt`/`.nc` SGML bundle that
concatenates the primary document and every exhibit, or a 1990s-era hand-authored HTML table
wrapped in presentational markup. This package is the first stage that turns either into text
another stage can reason about.

The invariant that shapes the whole package is that **a tagged `<TABLE>...</TABLE>` block must
survive byte-for-byte**. Whitespace healing, source-wrap collapsing, and tag decomposition all
run through `mask_tagged_tables` / `restore_tagged_tables` from
`edgar_sec/engine/tables/protection.py` so that later passes physically cannot see inside a
table span.

This package is pure. It performs no network I/O and writes no artifacts.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `unpacker.py` | SGML `<DOCUMENT>` envelope unpacking. `unpack_sgml_submission` returns one `SgmlSubDocument` per block (decoded latin-1, lossless); `resolve_target_sub_document` runs a four-tier target resolution; `extract_target_sub_document` re-scans raw bytes and slices out only the winner's payload without materializing the others; `strip_pem_envelope` removes the PEM transport wrapper. |
| `html.py` | `selectolax`-backed tree access. `parse_html` returns a `FastHtmlTree`; `FastHtmlNode` / `FastHtmlTree` are slotted wrappers giving a stable Python surface (`css`, `css_first`, `find_all`, `text`, `unwrap`, `decompose`, sibling/parent walks) over the C DOM. `normalize_html_document` renders HTML to normalized text. |
| `html_cleaner.py` | Stage-1 regex pre-cleaning and Stage-2 structural decomposition. `clean_html_for_parsing` runs six ordered strips (inline XBRL, font-qualified glyphs, benign styles, legacy font/noise attributes, office metadata, TOC jump-links); `decompose_html_structures` runs an eleven-step decomposition to plain text. Owns the tag classification sets `PARAGRAPH_TAGS`, `CONTAINER_BLOCK_TAGS`, `TABLE_AND_PRE_TAGS`, `BLOCK_TAGS`, `INLINE_TAGS`. |
| `page_markers.py` | Page-furniture detection and validated removal. `analyze_page_markers` returns a `PageMarkerAnalysis` of `PageMarker` occurrences plus per-marker `PageMarkerDecision`s; `strip_page_markers` applies only `REMOVE` decisions; `apply_text_policy` is the policy entry point. |
| `signatures.py` | Signature-layout primitives. `find_signature_regions` locates complete signature blocks line-preservingly; `mask_signature_regions` / `restore_signature_regions` hide and reinstate them while holding line count constant; `normalize_signature_marker` canonicalizes `/s/`; `heal_mangled_signature_text` repairs letter-spaced signature text. |
| `whitespace.py` | Final-text whitespace healing. `normalize_final_text_whitespace` strips line-end padding, splits concatenated bullets and footnotes onto their own lines, and collapses blank runs — all with table spans masked first. Also `split_concatenated_bullets` and the allocation-free `count_lines`. |

## Contracts

- **Tagged tables are never rewritten.** `html_cleaner.decompose_html_structures` masks every
  `<TABLE>` span before any pass runs and restores it after (`html_cleaner.py:488`, `:534`);
  `whitespace.normalize_final_text_whitespace` does the same
  (`whitespace.py:75`, `:79`). `restore_tagged_tables` raises `ValueError` if a sentinel is
  missing at restore time (`protection.py:180-183`) rather than silently returning a document
  with a lost table.
- **Masking is line-count preserving for signatures.** `mask_signature_regions` substitutes one
  `__SEC_SIG_{region}_{offset}__` token per line, so any line anchor computed against masked
  text still addresses the right line (`signatures.py:124-139`).
- **Decoding is latin-1 and lossless.** `unpack_sgml_submission` decodes with
  `latin-1, errors="replace"` (`unpacker.py:106-110`) and re-encodes payloads the same way, so
  a round trip is byte-identical. `parse_html` decodes as `utf-8` with `errors="replace"`
  (`html.py:303-305`).
- **Nothing raises on malformed input.** Every public function in this package returns `""`,
  `()`, `None`, or an empty analysis rather than raising. `unpack_sgml_submission("")` returns
  `[]`; `analyze_page_markers("")` returns a `NO_VISIBLE_LABELS` analysis; a signature-less
  document returns `()` from `find_signature_regions`.
- **Line coordinates are a published artifact.** `analyze_page_markers` populates
  `PageMarker.start_line` / `end_line` and `PageMarker.coordinate_frame`; `apply_text_policy`
  returns a tuple whose last element is the next free `first_id`, so a caller numbering several
  removed artifacts can continue from it. This is the input to
  `edgar_sec/engine/reflow/types.py::build_line_mapper` when reflow renumbers lines.
- **Layer discipline.** This package imports only from `domain`, `foundation`, and its sibling
  `engine.tables` and `engine.forms` packages. Enforced by the `layer-boundary` scanner.
- **Regex vocabulary is not hand-rolled.** Every 3+ branch alternation in
  `html_cleaner.py` and `signatures.py` is built with
  `edgar_sec.foundation.regex.builder.build_alternation`, per the `regex-alternations` scanner
  (`html_cleaner.py:98`, `:102`, `:385-387`; `signatures.py:22`, `:32-33`, `:38`).

## Public surface

- `SgmlSubDocument` — one extracted sub-document: `doc_type`, `sequence`, `filename`,
  `description`, `raw_payload`, `is_html`. `edgar_sec/engine/document/unpacker.py:39`.
- `unpack_sgml_submission` — parse an SGML envelope into all sub-documents.
  `edgar_sec/engine/document/unpacker.py:100`.
- `resolve_target_sub_document` — four-tier target resolution: target types, then primary
  filename, then `SEQUENCE 1`, then the first non-graphic text document.
  `edgar_sec/engine/document/unpacker.py:182`.
- `extract_target_sub_document` — the same resolution, but slicing the winner's payload directly
  out of the raw bytes so the others are never decoded. `edgar_sec/engine/document/unpacker.py:232`.
- `find_sub_document` — first sub-document matching target types or filename patterns.
  `edgar_sec/engine/document/unpacker.py:158`.
- `has_sgml_documents` — cheap bytes-level probe for a `<DOCUMENT>` block.
  `edgar_sec/engine/document/unpacker.py:93`.
- `strip_pem_envelope` — remove a leading `-----BEGIN PRIVACY-ENHANCED MESSAGE-----` wrapper.
  `edgar_sec/engine/document/unpacker.py:64`.
- `parse_html` — parse `str`/`bytes` into a `FastHtmlTree`. `edgar_sec/engine/document/html.py:301`.
- `FastHtmlNode` / `FastHtmlTree` — slotted `selectolax` wrappers. `edgar_sec/engine/document/html.py:20` and `:219`.
- `normalize_html_document` — render HTML to normalized text, returning a
  `NormalizedHtmlText` (a `str` subclass). `edgar_sec/engine/document/html.py:331`.
- `clean_html_for_parsing` — the six-step Stage-1 pre-clean entry point.
  `edgar_sec/engine/document/html_cleaner.py:371`.
- `decompose_html_structures` — the eleven-step block/inline decomposition to plain text.
  `edgar_sec/engine/document/html_cleaner.py:482`.
- `strip_ixbrl_inline_tags` — unwrap inline XBRL tags, drop `ix:header` and `ix:hidden` bodies.
  `edgar_sec/engine/document/html_cleaner.py:244`.
- `normalize_font_qualified_glyphs` — map Wingdings/Webdings/Symbol glyphs to canonical
  checkbox marks, scoped by an explicit font stack. `edgar_sec/engine/document/html_cleaner.py:255`.
- `strip_benign_font_styles`, `strip_office_metadata_attributes`,
  `strip_font_tag_and_noise_attributes`, `strip_toc_navigation_links` — the remaining four
  individual Stage-1 strips, each independently callable.
  `edgar_sec/engine/document/html_cleaner.py:316`, `:325`, `:337`, `:364`.
- `analyze_page_markers` — detect page furniture and decide per-marker actions.
  `edgar_sec/engine/document/page_markers.py:330`.
- `strip_page_markers` — apply only the validated `REMOVE` decisions.
  `edgar_sec/engine/document/page_markers.py:403`.
- `apply_text_policy` — policy entry point returning
  `(text, analysis, artifacts, extra, next_first_id)`. `edgar_sec/engine/document/page_markers.py:442`.
- `PageMarkerKind` — the 18 recognized marker shapes (`DASHED_NUMBER`, `PAGE_NUMBER_OF_TOTAL`,
  `APPENDIX_ROMAN`, `REPEATING_HEADER`, `REPEATING_FOOTER`, …).
  `edgar_sec/engine/document/page_markers.py:17`.
- `PageMarkerAction` / `PageArtifactPolicy` — `REMOVE|NORMALIZE|PRESERVE` and
  `STRIP|ANNOTATE|PRESERVE`. `edgar_sec/engine/document/page_markers.py:40` and `:56`.
- `find_signature_regions` / `mask_signature_regions` / `restore_signature_regions` — the
  signature layout triple. `edgar_sec/engine/document/signatures.py:70`, `:124`, `:142`.
- `heal_mangled_signature_text`, `normalize_signature_marker`,
  `signature_block_has_mangled_text`, `is_conformed_signature_line`,
  `is_signature_label_line` — signature text predicates and repair.
  `edgar_sec/engine/document/signatures.py:169`, `:154`, `:164`, `:175`, `:180`.
- `normalize_final_text_whitespace` — the final whitespace pass. `edgar_sec/engine/document/whitespace.py:67`.
- `split_concatenated_bullets` — the bullet/footnote split in isolation.
  `edgar_sec/engine/document/whitespace.py:56`.
- `count_lines` — newline count without materializing a line list. `edgar_sec/engine/document/whitespace.py:83`.

## Tests

The test tree mirrors the source tree (`AGENTS.md` §6); one file per source module:

- `tests/engine/document/test_unpacker.py` (106 lines)
- `tests/engine/document/test_html.py` (52 lines)
- `tests/engine/document/test_html_cleaner.py` (127 lines)
- `tests/engine/document/test_page_markers.py` (71 lines)
- `tests/engine/document/test_signatures.py` (54 lines)
- `tests/engine/document/test_whitespace.py` (50 lines)

## Deliberate gaps

- **The cover-page boundary is not here.** Deciding where the metadata stops and the body
  begins belongs to `edgar_sec/engine/forms/cover/` (`find_cover_boundary`,
  `find_body_start`, `find_closing_span`). This package supplies the text and the line
  coordinates; it makes no claim about what a filing's cover is.
- **v1's page-marker `candidates.py`, `vocabulary.py`, and `ascii/headers.py` have no v2
  home.** v1 shipped a 2,171-line `page_markers/` tree; v2's `page_markers.py` is 485 lines and
  implements the firm-marker scan and the repeating-header heuristic directly. The contextual
  candidate promotion, the cover-label vocabulary, and the local-cohort header/footer engine
  were **dropped, not ported**. This is the substitution roadmap
  `roadmap/refactor_v2/phase_2_5.md` §2 (workstream W2) records; the alternative when a
  candidate label needs the missing machinery is the heading-based transition in
  `engine/forms/cover/boundary.py::TOC_TRANSITION`, not a resurrected v1 module.
- **`PageCandidate` is a declared-but-unbuilt type.** `page_markers.py:84` defines it — start
  and end offsets, `family`, `namespace`, `value`, `relative_position`, `leading_column`,
  `template`, `exclusion` — and nothing in `edgar_sec/` or `tests/` ever constructs one. It is
  the shape v1's candidate-promotion scanner would have returned. Its presence is not evidence
  that contextual candidate scanning exists.
- **`PageArtifactPolicy.ANNOTATE` has no distinct behaviour.** `apply_text_policy`
  (`page_markers.py:455-458`) branches only on `PRESERVE`; `ANNOTATE` falls through to the
  strip path and behaves as `STRIP`. `PageMarkerAction.NORMALIZE` and
  `PageMarkerTerminalState.UNRESOLVED` are likewise never produced — `analyze_page_markers`
  emits only `NONE` and `NO_VISIBLE_LABELS`. The policy surface is a vocabulary awaiting an
  implementation, not a set of three working modes.
- **`analyze_page_markers`'s `context` parameter is inert.** It is accepted at
  `page_markers.py:332` and never read. A caller that passes candidate context expecting it to
  influence detection is passing nothing.
- **`NormalizedHtmlText.table_geometries` is always empty.**
  `normalize_html_document` constructs it with `()` at `html.py:343` and never populates it. The
  property exists so a caller can hold geometry alongside text, but on this path it is `()`.
  Geometry actually comes from
  `edgar_sec/engine/tables/ascii_html/__init__.py::convert_html_tables_to_ascii_with_metadata`,
  which returns `TableGeometry` values directly.
- **`split_concatenated_bullets` has no production caller.** It is the isolated form of the
  bullet split that `normalize_final_text_whitespace` performs internally
  (`whitespace.py:41-53`); only `tests/engine/document/test_whitespace.py` exercises it.
- **No v2 home for v1's `defs/text/bow/`.** The 1,234-line tiered bag-of-words engine was
  replaced by the single-tier Aho-Corasick automaton at
  `edgar_sec/foundation/text/automaton.py` (421 lines, Layer 0). This package does not consume
  it; the engine-layer consumer is `edgar_sec/engine/forms/cover/body_evidence.py`, which
  scores distinct hits onto **v1's same 0-3 scale** via `foundation.text.automaton.tier_confidence`
  (`automaton.py:55-61`). Roadmap `roadmap/refactor_v2/phase_2_5/04_engine_tables_and_forms.md`
  §4.1 records the substitution.
- **No golden-document regression gate in this package.** v1's empirical research lab —
  `HYPOTHESES.md` (435 lines) and `RULE_ENGINE_SPEC.md` (557 lines), both under
  `.v1/defs/text/reflow/tools/` — has **no v2 copy anywhere in the tree**
  (`find . -name RULE_ENGINE_SPEC.md` returns only the `.v1` original). Roadmap
  `v2_refactor_roadmap.md` §1.5 Tier 2 commits `testing/goldens/` and `check.py --goldens`; no
  such directory or flag exists. The v1 threshold derivations behind
  `FEATURE_GROUPS` in `edgar_sec/engine/reflow/registry.py` are therefore referenced but
  unpublished.
- **Nothing here fetches.** No HTTP, no cache, no rate limiting — that is
  `edgar_sec/infra/sec_http`. `edgar_sec/engine/document` starts from bytes already in hand.
