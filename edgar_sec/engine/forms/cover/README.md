# `edgar_sec/engine/forms/cover` — cover, body, and closing boundary detection

Answers one question in five positions: where does the cover page end and the filing body
begin, and what is in between. It owns the signal cascade, the backward confirmation that
keeps that cascade honest, the structural PART/ITEM matcher every other module leans on, and
the universal cover-field extractors.

It is not a checkbox solver. Candidate extraction, constraint solving, and rewrite live in
`edgar_sec/engine/forms/checkmarks/`; this package hands them a bounded line range and they
work inside it.

## Purpose

Turn "somewhere around here the metadata stops" into a defensible, evidence-backed line
number — conservative, corroborated, and expressed as an exclusive end. Detection is
directional: forward signals propose, a backward search confirms or pulls back.

This package does not rewrite text, does not reflow, and does not know which form it is
looking at beyond the `BoundarySignal` set its caller supplies.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | Frozen dataclasses and `StrEnum`s shared by every boundary decision: `CoverBoundary`, `BodyStart`, `CoverStart`, `BoundaryEvidence`, and the `BoundarySignal` / `BoundaryMethod` / `BodyAnchorType` enums. |
| `boundary.py` | `find_cover_boundary` — the five-signal forward cascade plus the corroboration rule, ending in a backward confirmation. Also owns `RE_TOC_HEADING` and `RE_INCORPORATED`. |
| `cover_start.py` | `find_cover_start` — the inclusive start of the cover-shaped cluster in the opening window. |
| `structure.py` | Generic, representation-neutral PART/ITEM heading mechanics. `match_structural_line` and `parse_section_heading`, plus the exact-heading predicates the detectors gate on. |
| `body_evidence.py` | Lexical body-prose scoring on v1's 0-3 scale, compiled as a single Aho-Corasick pass over the shared vocabulary. |
| `body_search.py` | The backward half: `find_body_root_backward` and `confirm_backward_body`, plus the strict/loose TOC-line predicates. |
| `body_start.py` | `find_body_start` — the forward search for a validated body anchor after the cover. |
| `closing.py` | `find_closing_span` — conservative detection of the signature / exhibit-index tail. |
| `extractors.py` | Universal cover-field extractors: company-name matching, EIN, fiscal period, commission file number. |

## The detection cascade

From `boundary.py:9-19` and `find_cover_boundary` (`boundary.py:440-624`), strongest signal
first, first confident hit wins:

1. `INCORPORATED_REFERENCE` — the annual/foreign cover reference block (`RE_INCORPORATED`,
   eleven incorporation phrasings built via `build_alternation`).
2. `TOC_TRANSITION` — a `TABLE OF CONTENTS` / `INDEX TO ...` / `EXHIBIT INDEX` heading
   (`RE_TOC_HEADING`) after cover evidence, corroborated by a first TOC row within
   `_TOC_TRANSITION_ROW_GAP = 10` lines.
3. `PART_FALLBACK` — an isolated `PART` heading after cover evidence.
4. `ITEM_FALLBACK` — a canonical `ITEM 1` heading after cover evidence.
5. `BODY_PROSE_FALLBACK` — decisive body-lexical prose with no structural anchor.

The load-bearing rule: **a literal phrase is never authoritative on its own.** Signals 2
through 5 all require corroborating prior cover evidence — either at least two cover identity
signals or a page marker — before they may fire (`boundary.py:521`, `:642`, `:709`). This
exists because filing bodies contain many isolated PART/ITEM headings, and a bare `PART I`
line means nothing without knowing the cover already ended.

The provisional end from a forward signal is then passed to `confirm_backward_body`
(`body_search.py:184`), which scans backwards for the first unambiguously-body line. A
nearby root confirms and records `backward_body_confirm`; a distant one means the forward
signal overshot, so the boundary is pulled back and the evidence records
`backward_body_adjust`.

## Contracts

- **Corroboration before action.** Every forward signal except `INCORPORATED_REFERENCE`
  needs prior cover evidence, and that signal needs it too. This is stated in the
  `find_cover_boundary` docstring (`boundary.py:447-453`) and enforced by the `identity_count`
  checks in each detector.
- **An empty `signals` tuple is a kill switch, not a default.** `find_cover_boundary` returns
  `_unknown_boundary(BoundaryMethod.DISABLED)` before touching the text
  (`boundary.py:454-455`). The docstring is explicit about why: so the checkmark solver is
  never handed a whole document as its cover region.
- **Every result is marked approximate.** `CoverBoundary.approximate` defaults to `True` and
  is set to `True` on every construction path in `boundary.py`. Callers that need a hard
  guarantee must not treat it as one.
- **Unknown is a real answer.** When no signal fires, `find_cover_boundary` returns a
  boundary with `end_line=None`, `method=BoundaryMethod.UNKNOWN`, `confidence=0.0`, and empty
  evidence (`_unknown_boundary`, `boundary.py:395`). It does not guess a line.
- **`is_toc_layout_line` is strict; `is_toc_like_line` is not, and they are not
  interchangeable.** `body_search.py:41-83` documents the trap: `RE_PAGE_NUMBER_SUFFIX` also
  matches a trailing Roman numeral, so a bare `PART I` satisfies it and v2's table-cell helper
  `looks_like_toc_row("PART I")` returns `True`. Table-cell TOC detection tolerates that
  because a lone `PART I` cell really is a TOC row; at line scope it is a heading. The
  strict variant is what validates structural heading candidates; the loose variant is v1's
  backward-search semantics and is never applied to a heading candidate.
  (Roadmap `phase_2_5/04_engine_tables_and_forms.md` §5 records this as a v2-specific trap that
  would otherwise have silently rejected every PART heading and disabled the fallbacks
  entirely.)
- **Body-start detection prefers a late, validated start over an early false one**
  (`body_start.py:3-6`). A late start may leave some prose hard-wrapped; an early start can
  corrupt a table, list, signature, or cover layout. A heading introducing nothing but a table
  or a blank run is rejected — the candidate is only accepted when substantive prose follows
  within `_HEADING_PROSE_WINDOW = 25` lines.
- **Closing detection is deliberately conservative, and absence means absence.** A missed
  closing region leaves ordinary body prose untouched; a false closing start can suppress body
  normalization (`closing.py:5-9`). `find_closing_span` returns `None` rather than guessing, and
  never reports a span inside a TOC or before the body. Callers must treat `None` as "no
  closing region detected" and leave the trailing content as ordinary body text.
- **Closing detection is form-neutral.** Form-specific item taxonomies (for example the 8-K
  `ITEM 9.01` exhibit list) stay with the owning form; this module only recognizes
  representation-level closing signals shared by all filings (`closing.py:12-14`).
- **Obligations on callers.** Callers pass the declared `BoundarySignal` tuple for the form
  and, when available, a `PageMarkerAnalysis` — the `PAGE_MARKERS` signal does nothing
  without one (`boundary.py:469`). The forward search is bounded at
  `max(200, len(lines) * 0.25)` lines (`boundary.py:464`), so a very long filing is not
  scanned end to end for a cover that should be in its first pages.

## Public surface

- `find_cover_boundary` — the five-signal cascade; keyword-only `signals`, `representation`, `page_analysis`. `edgar_sec/engine/forms/cover/boundary.py:440`.
- `find_cover_start` — the inclusive cover cluster start; takes a `CoverBoundaryPolicy`. `edgar_sec/engine/forms/cover/cover_start.py:113`.
- `find_body_start` — forward body anchor search with `search_window` defaulting to 300 lines. `edgar_sec/engine/forms/cover/body_start.py:187`.
- `find_closing_span` — the closing tail, searched from `search_from`. `edgar_sec/engine/forms/cover/closing.py:55`.
- `find_body_root_backward` / `confirm_backward_body` — the backward half, the reason a forward overshoot is corrected. `edgar_sec/engine/forms/cover/body_search.py:116` and `:184`.
- `is_toc_layout_line` / `is_toc_like_line` — the strict and loose TOC predicates. `edgar_sec/engine/forms/cover/body_search.py:41` and `:70`.
- `match_structural_line` — classify one line as a structural heading candidate. `edgar_sec/engine/forms/cover/structure.py:145`.
- `parse_section_heading` — parse a heading into a `ParsedSection`; `allow_inline=True` recognises a prose mention and flags `is_exact_heading=False`. `edgar_sec/engine/forms/cover/structure.py:191`.
- `is_continuation_prose` / `is_preceding_continuation` / `is_exact_heading` — the gates that separate a heading from prose that merely mentions a section. `edgar_sec/engine/forms/cover/structure.py:259`, `:282`, `:251`.
- `score_body_text` / `is_body_prose` / `is_semantic_heading` — lexical scoring, with `MIN_BODY_SCORE = 2` as the acceptance gate. `edgar_sec/engine/forms/cover/body_evidence.py:91`, `:134`, `:139`.
- `build_body_matcher` — compile the matcher over the shared vocabulary. `edgar_sec/engine/forms/cover/body_evidence.py:66`.
- `CoverBoundary`, `BodyStart`, `CoverStart`, `BoundaryEvidence`, `BodyStartEvidence`, `BoundarySignal`, `BoundaryMethod`, `BodyAnchorType`, `CoverBoundaryPolicy` — `edgar_sec/engine/forms/cover/models.py`.
- `match_company_name`, `normalize_ein`, `extract_candidate_ein`, `extract_fiscal_period`, `extract_commission_file_number`, `clean_company_name_string`, `get_core_name_tokens` — `edgar_sec/engine/forms/cover/extractors.py`.
- `RE_TOC_HEADING`, `RE_INCORPORATED`, `RE_TOC_NUMERIC_LABEL`, `RE_SIGNATURE_HEADING`, `RE_SLASH_S`, `RE_EXHIBIT_HEADING`, `RE_ITEM_EXACT`, `RE_PART` — compiled patterns exported by their defining modules.

The vocabulary itself is imported, not redefined: `COVER_LABELS_FLAT`,
`COVER_START_IDENTITY_TERMS`, and `COVER_START_SHAPE_TERMS` come from
`edgar_sec/domain/forms/vocabulary.py`; the body-prose tiers come from
`edgar_sec/domain/forms/body_evidence.py`; TOC row predicates come from
`edgar_sec/engine/tables/toc.py`.

## Tests

- `tests/engine/forms/cover/test_boundary.py` — 12 tests.
- `tests/engine/forms/cover/test_body_start.py` — 9 tests.
- `tests/engine/forms/cover/test_body_evidence.py` — 10 tests.
- `tests/engine/forms/cover/test_closing.py` — 8 tests.
- `tests/engine/forms/cover/test_structure.py` — 11 tests.
- `tests/engine/forms/cover/test_extractors.py` — 9 tests.
- Indirect coverage of the cascade: `tests/engine/forms/test_normalize.py` and `tests/engine/forms/test_normalization_goldens.py`.

## Deliberate gaps

- **No v2 TOC span finder, and no port of one.** v1's `defs/sec_forms/cover/toc/` measured
  938 loc across six modules and included `find_toc_span`, its confidence refinement. That
  capability was **dropped rather than relocated**. v2 reuses only the TOC *primitives* that
  `edgar_sec/engine/tables/toc.py` already provides — `looks_like_toc_row`,
  `looks_like_toc_tabular`, `RE_ITEM_REFERENCE` — so the `TOC_TRANSITION` signal still fires
  but **one signal later than v1 and without the `find_toc_span` confidence refinement**
  (`boundary.py:21-28`). The practical consequence is stated in
  `edgar_sec/engine/forms/normalize.py:29-30`: body-start detection is anchored on cover end
  alone.
- **`DocumentTopology` has no producer.** The v1 four-zone record (cover start/end, TOC
  start/end, body start) is declared at `models.py:118` and exported in `__all__`, but
  nothing in `edgar_sec/` or `tests/` constructs or consumes it — verified by a repo-wide
  symbol grep. It is a declared type with no role today; do not infer that a TOC zone was
  resolved. `ItemDefinition` (`models.py:107`) and `BodyRoot` (`models.py:97`) are in the
  same state: `find_body_root_backward` returns a plain `(line, root_type, confidence)`
  tuple, not a `BodyRoot`. `BoundaryInput` (`models.py:79`) is likewise unused —
  `find_cover_boundary` takes keyword arguments instead.
- **The tiered bag-of-words lexical engine was substituted, not ported.** v1's
  `defs/text/bow/` measured 1,234 loc across five modules: a four-tier weighted engine with
  per-tier minimum-distinct-hit thresholds and per-form packs. v2's
  `edgar_sec/foundation/text/automaton.py` (421 loc) compiles **one tier per category**, so
  v1's structure cannot be reproduced as written. `body_evidence.py` collapses the four tiers
  into one distinct-hit count scored onto **v1's same 0-3 scale**: 0–1 weak, 2 accepted,
  3+ decisive (`body_evidence.py:9-28`). One decisive strong phrase still scores 3
  regardless of breadth, mirroring v1's "one distinct phrase hit confirms body prose" rule.
  The cover-exclusion veto is preserved and stronger than a tier weight: a paragraph carrying
  a `COVER_EXCLUSION_TERMS` label scores 0 outright, however much narrative vocabulary it also
  contains (`body_evidence.py:101-102`). **This package does consume the shared vocabulary**
  in `edgar_sec/domain/forms/body_evidence.py` — six tier tuples plus the exclusion and
  semantic-heading sets. Per-form evidence packs do not exist in v2.
- **No logical-unit classifier.** v1's `find_body_start` called `classify_units` to learn
  whether a candidate line sat in a table, list, signature, or TOC unit. Unit context is
  approximated by line-level structural and lexical gates that encode the same distinctions
  (`body_start.py:20-27`). The abstraction is gone; the distinctions are not.
- **No cover healing and no cover-page semantic model.** v1 had
  `cover/healing.py::heal_cover_text()` (representation-neutral cover healing applying
  checkbox, phrase-sequence, and date healing to a bounded cover slice) and
  `defs/sec_forms/models.py` (`CoverPageModel`, `Security12b`, `RegistrantEntry`,
  `CheckboxDisclosures`). Neither has a v2 home in this package; there is no
  `heal_cover_text` symbol anywhere in `edgar_sec/`.
- **No cover profile registry and no form-specific taxonomies.** v1's `cover/profiles.py`
  held `CoverProfile` / `COVER_PROFILES` / `get_profile()`. In v2 the equivalent per-form data
  is the `FormPlugin` in `edgar_sec/engine/forms/plugins/`, and the Part/Item taxonomies were
  not ported. `structure.py` is deliberately generic: its `RE_PART_REFERENCE` and
  `RE_ITEM_REFERENCE` accept Roman or decimal labels so a future form can add them without
  editing this module (`structure.py:99-101`).
- **No `body_context.py`-style unit indexing.** v1's `cover/body_context.py` (127 loc) was
  folded into `body_start.py` rather than ported as its own module (roadmap §4, M4.3 table).
- **The forward search window is bounded and unconfigurable.** `_SEARCH_WINDOW_FLOOR = 200`,
  `max(200, 25% of lines)` for the boundary, `300` for the body start. A cover that begins
  more than a quarter into a very long document will not be found. This is a deliberate cost
  bound, not a TODO.
- **`extractors.py` has no production caller.** Its seven public functions are exercised only
  by `tests/engine/forms/cover/test_extractors.py`; nothing in `edgar_sec/` calls them today.
  It is a retained universal-extractor surface, not an oversight — but do not assume the
  normalization chain routes through it.
- **No page markers here.** v1's `defs/sec_forms/page_markers/` (a 16-module tree) did not
  move to this package; that responsibility is `edgar_sec/engine/document/page_markers.py`
  (485 loc), a sibling package in Layer 3. This package only *consumes* its
  `PageMarkerAnalysis`. See that package's own README for its contract.
