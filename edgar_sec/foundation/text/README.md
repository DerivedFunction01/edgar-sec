# `edgar_sec/foundation/text` — shared text vocabulary: dates, tokens, grammar, compounds, and the Aho-Corasick automaton

This package owns the pattern vocabulary that more than one layer needs: month
tables and the ordered SEC date formats, bullet and roman-numeral tokens, the
English closed-class word lists, Unicode whitespace normalisation, Cartesian
phrase generation, and a token-level multi-pattern automaton. It is the single
answer to "what does this month table look like", enforced by the `date-patterns`
scanner. It is not a document parser and it knows nothing about filings.

## Purpose

Text processing in this repository has two failure modes. The first is a second
private answer to a shared question — a module with its own month list, its own
bullet characters, its own whitespace rules — which drifts silently and
eventually surfaces as a mis-partitioned dataset rather than as a crash. The
second is re-deriving the same shape of work: tokenize, normalise, expand phrase
variants, scan for many patterns at once.

`text/` answers both. `dates.py` and `tokens.py` own the vocabularies, and two
scanners — `date-patterns` and `regex-alternations` — make a private copy a
failing build. `automaton.py` owns the single-pass matcher so no consumer writes
a second one.

What this package is not: it does not parse documents, does not handle HTML or
SGML structure, and does not classify filing types. Those belong to
`engine/document/`, `engine/forms/`, and `engine/tables/`.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `automaton.py` | Token-level Aho-Corasick automaton, lexical matcher, and classification (421 loc). |
| `compounds.py` | Cartesian compound phrases, plural and US/UK variants, term normalisation (169 loc). |
| `dates.py` | Month tables, ordered SEC date formats, year expansion, year extraction (448 loc). |
| `grammar.py` | English closed-class words and prose grammar patterns (233 loc). |
| `normalize.py` | Unicode whitespace sanitisation and blank-line compaction (71 loc). |
| `patterns.py` | Domain-neutral line-shape regexes: leaders, column gaps, separators (47 loc). |
| `tokens.py` | Bullet and ordered markers, footnote marks, Roman numeral conversion (147 loc). |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

`text/` is one of only two path prefixes the `regex-alternations` scanner
exempts, the other being `edgar_sec/foundation/regex/`. Every multi-branch
alternation in this package is built through
`edgar_sec.foundation.regex.builder`, never written by hand.

## Contracts

**Guarantees this package makes to its callers**

- `dates.py` is the sole owner of month vocabulary. `MONTH_NAMES` is the twelve
  full names; `MONTH_ALIASES` is the ordered per-month alias tuple, and both
  `_MONTH_NAME_TO_INDEX` and `MONTH_PATTERN` are derived from `MONTH_ALIASES` in
  one loop, so a new alias cannot be added to one and forgotten in the other
  (`dates.py:44-48`). `MONTH_PATTERN` is built with
  `build_alternation(..., auto_escape=True, compact=True)`.
- `SEC_DATE_FORMATS` is an ordered, prioritised tuple of seven `DateFormat`
  records. `parse_date()` sorts by `priority` descending and returns the first
  format whose pattern matches *and* whose year, month, and day all survive
  validation (`dates.py:264-303`). A partial match is skipped, not returned.
- `parse_date()` returns `None` rather than raising on unparseable input, and it
  rejects a year outside `YEAR_RANGE` `(1900, DEFAULT_YEAR_UPPER_BOUND)` where
  the upper bound is `max(2100, current_year + 50)` — a rolling bound, not a
  constant.
- `DateComponents.valid()` confirms the date exists by constructing
  `datetime.date`, so `31 February` is rejected rather than stored.
- `ParsedDate.iso` renders `YYYY-MM-DD` zero-padded; `ParsedDate.display`
  returns the source substring that matched.
- `expand_2digit_year()` uses a rolling window: the base year is
  `anchor - lookback_years` (default 80), the century comes from that base, and
  the result is bumped a century if it would fall before the window. Passing
  `century_pivot` switches to fixed pivot behaviour instead. A year of 100 or
  more is returned unchanged.
- `extract_years()` returns a list, in document order, of years validated
  against `valid_range`, with 1- and 2-digit captures routed through
  `expand_2digit_year`.
- `sanitize_unicode_whitespace()` strips every character in `STRIP_ZERO_WIDTH`
  (16 zero-width, bidi-control, and isolate characters including the BOM) and
  replaces every character in `NORMALIZE_TO_SPACE` (no-break space, figure
  space, narrow no-break space, thin space) with an ASCII space. Order matters
  and is fixed: strip first, then normalise.
- `collapse_whitespace()` collapses runs of spaces and tabs to one and strips the
  ends. `collapse_excessive_blank_lines()` collapses three or more newlines to
  two, which is the paragraph separator. Both return `""` for empty input.
- `tokenize()` produces `Token` records carrying both a `surface` and a
  `folded` (lowercased) view, so a caller can match case-insensitively and still
  verify the original spelling. It returns `[]` for empty input.
- `tokenize()` first maps seven dash characters — hyphen-minus, U+2010 through
  U+2014, and U+2212 — to a space (`automaton.py:11-12, 38`). Consequently
  `Token.start` and `Token.end` are offsets into the *translated* string, not
  into the caller's original text.
- `compile_lexical_matcher(categories, exclusions=None)` builds one automaton
  for all categories in a single pass: transitions, BFS failure links, and
  output propagation from failure states (`automaton.py:380-398`).
- `scan_tokens()` runs the whole token sequence in one pass and returns
  `(end_position, MatchPayload)` for every match, including matches recovered
  through a failure link.
- `has_any()` short-circuits on the first non-exclusion match and honours an
  optional category filter, so a cheap "does this document mention any of
  these?" never pays for full classification.
- `classify()` picks the best-scoring category by `tier_confidence()`, breaking
  ties on the higher raw score, and returns a `ClassificationMatch` with
  `category=None` and a reason string when nothing matched.
- `tier_confidence(value, distinct_hits)` is the calibrated 0-3 scale: a tier
  value of 3 yields `min(0.98, 0.9 + 0.02 * distinct_hits)`, a value of 2 yields
  `min(0.95, 0.8 + 0.03 * distinct_hits)`, and anything lower yields
  `min(0.6, 0.45 + 0.05 * distinct_hits)`, all rounded to four places.
- `is_list_or_bullet_marker()` returns `False` for a bare undelimited English
  word such as `a` or `I`, so the letter-listener `a.` is distinguished from the
  article `a`.
- `roman_to_int()` accepts only a canonical, bounded Roman numeral: it
  re-encodes the parsed total and returns `None` unless the encoding matches the
  input, so `IIII` and `IC` are both rejected. Values outside `(0, 3000]` are
  rejected.
- `expand_alternations()` normalises terms to lowercase, collapses internal
  whitespace, deduplicates, and orders by `(-word_count, -char_length, term)` —
  with an alphabetical tie-breaker the regex DSL does not use, so phrase lists
  are byte-stable.
- `expand_variants()` derives English plural forms (`-es` after s/sh/ch/x/z,
  `-y` to `-ies` after a consonant, `-man` to `-men`, otherwise `-s`) and swaps
  `-or`/`-our` spellings. It is a mechanical rule set, not a stemmer.
- `expand_compounds(*slots, sep=" ")` takes the Cartesian product of its slots.
  A slot that is `None`, or a collection containing `None` or `""`, is treated as
  optional and contributes an empty alternative, so the empty combination is
  dropped rather than producing a phrase with a double separator.

**Obligations callers place on this package**

- Do not define a private month table, an inline month sequence, a hand-written
  month alternation, or a hand-written `\d{1,2}/\d{1,2}/\d{2,4}`-style date
  pattern. The `date-patterns` scanner exempts exactly one module,
  `edgar_sec/foundation/text/dates.py`, and its hint points at `MONTH_PATTERN`,
  `MONTH_NAMES`, `parse_date`, and `SEC_DATE_FORMATS`.
- Do not write a raw 3+ branch alternation here expecting to be exempt from the
  scanner's *intent* — this path is allowlisted only because it is where the
  vocabulary legitimately lives. Use `build_alternation`,
  `build_compound`, or `compact_alternation`; every alternation in this package
  already does.
- When using `Token.start` / `Token.end` as source offsets, remember they index
  the dash-translated string. A caller needing offsets into the original text
  must re-derive them.
- A `ClassMode` of `exact` or `lowercase` is enforced against the token surfaces
  at match time in `scan_tokens()` and `scan_family_hits()`; `fold` is the
  default and is the cheap path.
- An exclusion anywhere in a category's hits disqualifies that category entirely
  in `classify()` — exclusions are not subtractive.

## Public surface

- `MONTH_NAMES` / `MONTH_ALIASES` / `MONTH_PATTERN` / `MONTH_RE` / `MONTH_NAME_RE` / `month_name_to_index` — the month vocabulary and its only owner. `dates.py`.
- `SEC_DATE_FORMATS` — the ordered tuple of seven prioritised `DateFormat` records. `dates.py`.
- `DateFormat` / `DateComponents` / `ParsedDate` — the date value types; `DateComponents.to_iso()` and `.valid()`, `ParsedDate.iso` and `.display`. `dates.py`.
- `parse_date` — resolve a complete date string against `SEC_DATE_FORMATS`. `dates.py`.
- `expand_2digit_year` / `parse_year_token` / `parse_numeric_year` / `extract_years` — year resolution, all routed through `YEAR_RANGE`. `dates.py`.
- `is_valid_year` / `is_year_token` / `contains_date` — predicates. `dates.py`.
- `YEAR_RANGE` / `DEFAULT_YEAR_UPPER_BOUND` / `YEAR_TOKEN_PATTERN` / `RE_FULL_DATE` / `PERIOD_SUBHEADING_RE` / `COLUMN_YEAR_ROW_RE` / `TABLE_YEAR_RE` — header and period-header shapes. `dates.py`.
- `tokenize` / `Token` — single-pass tokenization keeping surface and folded views. `automaton.py`.
- `MultiPatternAutomaton` with `scan_tokens` and `scan_family_hits` — the compiled state machine. `automaton.py`.
- `LexicalMatcher` with `has_any`, `find_matches`, and `classify`. `automaton.py`.
- `compile_lexical_matcher` / `tier_confidence` — automaton construction and the 0-3 confidence scale. `automaton.py`.
- `MatchPayload` / `MatchedTerm` / `ClassificationMatch` / `CaseMode` — the match value types. `automaton.py`.
- `expand_alternations` / `expand_variants` / `expand_compounds` — phrase generation. `compounds.py`.
- `sanitize_unicode_whitespace` / `collapse_whitespace` / `collapse_excessive_blank_lines` / `NORMALIZE_TO_SPACE` / `STRIP_ZERO_WIDTH`. `normalize.py`.
- `ARTICLES` / `RELATIVE_PRONOUNS` / `FUNCTION_WORDS` / `TRAILING_CONNECTORS` / `PROSE_TRANSITION_PHRASES` and their compiled patterns `RE_ARTICLE`, `RE_RELATIVE_PRONOUN`, `RE_TRAILING_CONNECTOR`, `RE_PROSE_TRANSITION_PHRASE`, `RE_POSSESSIVE`, `RE_VERBAL_PARTICIPLE`, `RE_WORD_TOKEN`. `grammar.py`.
- `BULLET_MARKERS` / `GLYPH_BULLET_MARKERS` / `BULLET_MARKER_RE` / `DELIMITED_ORDERED_MARKER_RE` / `WRAPPED_ORDERED_MARKER_RE` / `BRACKETED_ORDERED_MARKER_RE` / `ORDERED_MARKER_PREFIX_RE` / `WRAPPED_MARKER_PREFIX_RE` / `FOOTNOTE_MARKERS` / `FOOTNOTE_MARKER_RE` / `ROMAN_NUMERAL_PATTERN` and the predicates `is_list_or_bullet_marker`, `is_bullet_line`, `is_ordered_marker_prefix`, `is_wrapped_marker_prefix`, `roman_to_int`. `tokens.py`.
- `RE_DOT_LEADER` / `RE_COLUMN_GAP` / `RE_PAGE_NUMBER_SUFFIX` / `RE_GRAMMATICAL_COMMA` / `RE_SENTENCE_TERMINAL` / `RE_TERMINAL_BOUNDARY` / `RE_SEPARATOR_RUN` / `RE_SEPARATOR_LINE` / `RE_FILL_IN_RUN` / `RE_TRAILING_FILL_IN` / `RE_WHITESPACE` / `RE_NON_ALNUM` / `RE_STRUCTURAL_SGML` / `PAGE_NUMBER_CORE` / `CONTINUATION_PUNCTUATION`. `patterns.py`.

## Tests

- `tests/foundation/text/test_automaton.py`
- `tests/foundation/text/test_compounds.py`
- `tests/foundation/text/test_dates.py`
- `tests/foundation/text/test_grammar.py`
- `tests/foundation/text/test_normalize.py`
- `tests/foundation/text/test_patterns.py`
- `tests/foundation/text/test_tokens.py`

The two scanners that keep this package authoritative are tested at
`tests/foundation/scanners/test_date_patterns.py` and
`tests/foundation/scanners/test_regex_alternations.py`.

## Deliberate gaps

- **The tiered bag-of-words engine was replaced, not ported.** v1 carried
  `.v1/defs/text/bow/` at 1,234 lines across `engine.py` (494), `automaton.py`
  (474), `match.py` (106), and `types.py` (84), with per-tier compiled token
  indexes, `band_max_value`, and windowed matching. v2 keeps the Aho-Corasick
  core and drops the tier structure: `compile_lexical_matcher()` assigns every
  phrase the single tier `("primary", (3, 1, False))` — one tier, value 3,
  minimum one distinct hit (`automaton.py:327-341`). The 0-3 scale survives in
  `tier_confidence()` and in the `tier_requirements` field of `LexicalMatcher`,
  so a caller can populate several tiers itself, but nothing in the repository
  does. This is a deliberate substitution, not an oversight: the multi-tier
  compilation machinery bought precision the v2 callers do not yet use, at four
  modules' worth of maintenance.
- **Tier-exclusion evidence is collected and then discarded.** `classify()`
  computes the matching category's exclusion terms and uses them to skip the
  category, but `best_excl_hits` is initialised to `()` and never reassigned, so
  `ClassificationMatch.exclusion_terms` is always empty
  (`automaton.py:253, 309`). The data model advertises the field; nothing
  populates it.
- **`MatchPayload.min_distinct_hits` is written and never read.** It is set to
  `1` at every construction site. `classify()` takes its minimum-distinct
  requirement from `LexicalMatcher.tier_requirements` instead, with a `(2, 1,
  False)` default for an unregistered tier. A caller setting `min_distinct_hits`
  on a payload will see no effect.
- **`CaseMode` is a declaration, not a mechanism.** The `StrEnum` is defined and
  exported, but the automaton compares the raw strings `"exact"` and
  `"lowercase"` in two places and never references the enum. Use the string
  values; the enum is documentation.
- **No stemming, lemmatisation, or fuzzy matching.** `expand_variants()`
  implements four plural rules and an `-or`/`-our` swap. There is no
  Porter-style stemmer, no edit distance, and no n-gram index, so `derivative`
  and `derivatives` match only because the caller expanded the list.
- **No per-document parallelism.** The automaton is a single-threaded data
  structure. Batching and threading belong to the caller; nothing here
  parallelises a scan.
- **Dropped from v1, by design.** Not ported into this package:
  `defs/text/healing/` (soft-wrap line joining, Yes/No checkbox block
  normalisation, bullet split normalisation, paragraph compaction),
  `defs/text/html/` (the string-first HTML pipeline, tag canonicalisation, table
  protection, iXBRL stripping), `defs/text/structure/logical_units.py` (the
  `LogicalUnit` classification — there is no `LogicalUnit` anywhere in v2), and
  `defs/text/reflow/tools/` (the analysis, clustering, and experimental-registry
  suites). Where the behaviour survived the migration it moved up a layer:
  `engine/reflow/` holds the block segmentation and
  `UNWRAP`/`PRESERVE`/`TAG_AND_PRESERVE` decision dispatch, `engine/document/`
  holds `html.py`, `html_cleaner.py`, `page_markers.py`, `signatures.py`,
  `unpacker.py`, and `whitespace.py`, `engine/forms/checkmarks/` holds the
  checkbox extraction and Yes/No rewrite, and `engine/tables/ascii_html/` holds
  the table geometry and rendering. Those are Layer 3 concerns by design: the
  document pipeline is not a shared utility.
  `LogicalUnit` classification and the clustering/analysis tooling have no v2
  home at all and are unbuilt rather than relocated.
- **No word-frequency or TF-IDF machinery.** The package produces matches and a
  confidence score; it does not count term frequencies across a corpus or
  weight them.
- **No command surface.** There is no `__main__.py` and no entry point. Every
  symbol is imported by a higher layer.
