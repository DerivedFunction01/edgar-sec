# `edgar_sec/foundation/text` — shared text vocabulary

Pattern vocabulary more than one layer needs: month tables and the ordered SEC
date formats, bullet and roman-numeral tokens, the English closed-class word
lists, Unicode whitespace normalisation, Cartesian phrase generation, soft-wrap
line healing, and a token-level multi-pattern automaton. It is the single answer
to "what does this month table look like", enforced by the `date-patterns`
scanner. It does not parse documents and knows nothing about filings.

## Layout

| Module | Responsibility |
| :--- | :--- |
| [`automaton.py`](automaton.py) | Token-level Aho-Corasick automaton, lexical matcher, evidence-family compilation, classification. |
| [`dates.py`](dates.py) | Month tables, ordered SEC date formats, year expansion and extraction. |
| [`evidence.py`](evidence.py) | Token-boundary lexical evidence packs and the capped 0-3 tier scorer. |
| [`compounds.py`](compounds.py) | Cartesian compound phrases, plural and US/UK variants, term normalisation. |
| [`grammar.py`](grammar.py) | English closed-class words and prose grammar patterns. |
| [`healing.py`](healing.py) | Soft-wrap line joining: phrase-sequence rules, trailing-continuation and negative-boundary guards. |
| [`normalize.py`](normalize.py) | Unicode whitespace sanitisation and blank-line compaction. |
| [`patterns.py`](patterns.py) | Domain-neutral line-shape regexes: leaders, column gaps, separators. |
| [`tokens.py`](tokens.py) | Bullet and ordered markers, footnote marks, Roman numeral conversion. |
| `__init__.py` | One-line docstring. No re-exports, per AGENTS.md §1.2. |

`text/` is one of only two path prefixes the `regex-alternations` scanner exempts,
the other being [`foundation/regex/`](../regex/README.md). Every multi-branch
alternation here is built through `edgar_sec.foundation.regex.builder`, never
written by hand.

## Contracts

**Guarantees to callers**

- `dates.py` is the sole owner of month vocabulary. `_MONTH_NAME_TO_INDEX` and
  `MONTH_PATTERN` are both derived from `MONTH_ALIASES` in one loop, so a new
  alias cannot be added to one and forgotten in the other.
- `SEC_DATE_FORMATS` is an ordered tuple of seven prioritised `DateFormat`
  records. `parse_date()` sorts by `priority` descending and returns the first
  format whose pattern matches *and* whose year, month, and day all survive
  validation. A partial match is skipped, not returned.
- `parse_date()` returns `None` rather than raising on unparseable input, and
  rejects a year outside `YEAR_RANGE` `(1900, DEFAULT_YEAR_UPPER_BOUND)`, where
  the upper bound is `max(2100, current_year + 50)` — a rolling bound.
- `DateComponents.valid()` confirms the date exists by constructing
  `datetime.date`, so `31 February` is rejected rather than stored.
  `ParsedDate.iso` renders `YYYY-MM-DD`; `.display` returns the matched source
  substring.
- `expand_2digit_year()` uses a rolling window: the base year is
  `anchor - lookback_years` (default 80) and a candidate that would fall before
  it is bumped a century. Passing `century_pivot` switches to fixed-pivot
  behaviour. A year of 100 or more is returned unchanged.
- `extract_years()` returns years in document order, validated against
  `valid_range`, with 1- and 2-digit captures routed through
  `expand_2digit_year`.
- `sanitize_unicode_whitespace()` strips every character in `STRIP_ZERO_WIDTH`
  (16 zero-width, bidi-control, and isolate characters including the BOM), then
  replaces every character in `NORMALIZE_TO_SPACE` (no-break, figure, narrow
  no-break, thin space) with an ASCII space. Order is fixed: strip, then
  normalise.
- `tokenize()` produces `Token` records carrying both a `surface` and a `folded`
  view. It first maps seven dash characters — hyphen-minus, U+2010 through
  U+2014, and U+2212 — to a space, so `Token.start` / `Token.end` are offsets
  into the *translated* string, not the caller's original text.
- `compile_lexical_matcher(categories, exclusions)` builds one automaton for all
  categories in a single pass: transitions, BFS failure links, and output
  propagation from failure states. Every phrase gets the single tier
  `("primary", (3, 1, False))`.
- `compile_family_automaton(specs)` builds one automaton from a sequence of
  evidence packs, emitting a `MatchPayload` per term carrying its tier name,
  value, support flag, token length, and case mode, plus one payload per
  exclusion term. A tier with no `terms` falls back to its precompiled
  `unigrams` / `ngram_index`.
- `scan_tokens()` runs the whole sequence in one pass and returns
  `(end_position, MatchPayload)` for every match, including matches recovered
  through a failure link.
- `has_any()` short-circuits on the first non-exclusion match and honours a
  category filter, so "does this document mention any of these?" never pays for
  full classification.
- `classify()` picks the best-scoring category by `tier_confidence()`, breaking
  ties on the higher raw score, and returns a `ClassificationMatch` with
  `category=None` and a reason string when nothing matched.
- `tier_confidence(value, distinct_hits)` is the calibrated 0-3 scale: value 3
  yields `min(0.98, 0.9 + 0.02 * n)`, value 2 yields `min(0.95, 0.8 + 0.03 * n)`,
  anything lower `min(0.6, 0.45 + 0.05 * n)` — rounded to four places.
- `is_list_or_bullet_marker()` returns `False` for a bare undelimited English
  word such as `a` or `I`, distinguishing the letter-listener `a.` from the
  article.
- `roman_to_int()` accepts only a canonical bounded Roman numeral: it re-encodes
  the parsed total and returns `None` unless the encoding matches the input, so
  `IIII` and `IC` are rejected. Values outside `(0, 3000]` are rejected.
- `expand_alternations()` lowercases, collapses internal whitespace, dedupes, and
  orders by `(-word_count, -char_length, term)` — with an alphabetical tie-breaker
  the regex DSL does not use, so phrase lists are byte-stable.
- `expand_variants()` applies four mechanical plural rules (`-es` after
  s/sh/ch/x/z, `-y` to `-ies` after a consonant, `-man` to `-men`, else `-s`) and
  swaps `-or`/`-our`. It is not a stemmer.
- `expand_compounds(*slots, sep=" ")` takes the Cartesian product of its slots. A
  `None` slot, or a collection containing `None` or `""`, is optional and
  contributes an empty alternative, so the empty combination is dropped rather
  than yielding a double separator.
- `heal_split_lines()` preserves the original leading whitespace of each
  emitted line, so cover orientation (centering, two-column captions) survives
  healing. It joins a line only when `should_join_two_lines()` agrees: a negative
  boundary term, a bracketed continuation, a `<`-prefixed line, or an explicit
  phrase rule all veto the join. The trailing-continuation fallback is
  deliberately conservative — it only joins lowercase continuation text, so a
  title-cased caption reads as a new field.

**Obligations on callers**

- Do not define a private month table, inline month sequence, hand-written month
  alternation, or `\d{1,2}/\d{1,2}/\d{2,4}`-style pattern. The `date-patterns`
  scanner exempts exactly one module, `edgar_sec/foundation/text/dates.py`.
- Do not write a raw 3+ branch alternation here expecting exemption from the
  scanner's *intent* — this prefix is allowlisted because it is where the
  vocabulary legitimately lives. Use `build_alternation`, `build_compound`, or
  `compact_alternation`.
- When using `Token.start` / `Token.end` as source offsets, remember they index
  the dash-translated string. Re-derive them if you need original offsets.
- An exclusion anywhere in a category's hits disqualifies that category entirely
  in `classify()`. Exclusions are not subtractive.
- `PhraseSequenceRule.tokens` entries that are plain strings are passed through
  the DSL **unescaped** when they contain `|` or start with `\d`, and `re.escape`d
  otherwise. A literal string containing regex metacharacters is a footgun here.

## Public surface

Import from the leaf module.

- [`dates.py`](dates.py): `MONTH_NAMES`, `MONTH_ALIASES`, `MONTH_PATTERN`,
  `MONTH_RE`, `MONTH_NAME_RE`, `month_name_to_index`, `SEC_DATE_FORMATS`,
  `DateFormat`, `DateComponents`, `ParsedDate`, `parse_date`,
  `expand_2digit_year`, `parse_year_token`, `parse_numeric_year`,
  `extract_years`, `is_valid_year`, `is_year_token`, `contains_date`,
  `YEAR_RANGE`, `DEFAULT_YEAR_UPPER_BOUND`, `YEAR_TOKEN_PATTERN`,
  `RE_FULL_DATE`, `PERIOD_SUBHEADING_RE`, `COLUMN_YEAR_ROW_RE`, `TABLE_YEAR_RE`.
- [`automaton.py`](automaton.py): `tokenize`, `Token`, `MultiPatternAutomaton`
  (`scan_tokens`, `scan_family_hits`), `LexicalMatcher` (`has_any`,
  `find_matches`, `classify`), `compile_lexical_matcher`,
  `compile_family_automaton`, `tier_confidence`, `MatchPayload`, `MatchedTerm`,
  `ClassificationMatch`, `CaseMode`.
- [`evidence.py`](evidence.py): `EvidenceTier`, `LexicalEvidencePack`,
  `EvidenceContext`, `EvidenceHit`, `BowScore`, `CompiledTier`,
  `CompiledEvidencePack`, `compile_evidence_pack`, `score_tokens`, `score_unit`,
  `normalize_tokens`, `band_max_values`, `build_reason`, `tier_confidence`,
  `match_unigrams`, `match_ngrams`, `token_to_key`, `window_key`.
- [`compounds.py`](compounds.py): `expand_alternations`, `expand_variants`,
  `expand_compounds`.
- [`grammar.py`](grammar.py): `ARTICLES`, `RELATIVE_PRONOUNS`, `FUNCTION_WORDS`,
  `TRAILING_CONNECTORS`, `PROSE_TRANSITION_PHRASES`, `RE_ARTICLE`,
  `RE_RELATIVE_PRONOUN`, `RE_TRAILING_CONNECTOR`, `RE_PROSE_TRANSITION_PHRASE`,
  `RE_POSSESSIVE`, `RE_VERBAL_PARTICIPLE`, `RE_WORD_TOKEN`.
- [`healing.py`](healing.py): `PhraseSequenceRule`, `heal_split_lines`,
  `should_join_two_lines`, `normalize_whitespace_and_tabs`,
  `strip_alphanumeric_words`, `NEGATIVE_BOUNDARY_RE`.
- [`normalize.py`](normalize.py): `sanitize_unicode_whitespace`,
  `collapse_whitespace`, `collapse_excessive_blank_lines`, `NORMALIZE_TO_SPACE`,
  `STRIP_ZERO_WIDTH`.
- [`tokens.py`](tokens.py): `BULLET_MARKERS`, `GLYPH_BULLET_MARKERS`,
  `BULLET_MARKER_RE`, `DELIMITED_ORDERED_MARKER_RE`, `WRAPPED_ORDERED_MARKER_RE`,
  `BRACKETED_ORDERED_MARKER_RE`, `ORDERED_MARKER_PREFIX_RE`,
  `WRAPPED_MARKER_PREFIX_RE`, `FOOTNOTE_MARKERS`, `FOOTNOTE_MARKER_RE`,
  `ROMAN_NUMERAL_PATTERN`, `is_list_or_bullet_marker`, `is_bullet_line`,
  `is_ordered_marker_prefix`, `is_wrapped_marker_prefix`, `roman_to_int`.
- [`patterns.py`](patterns.py): `RE_DOT_LEADER`, `RE_COLUMN_GAP`,
  `RE_PAGE_NUMBER_SUFFIX`, `RE_GRAMMATICAL_COMMA`, `RE_SENTENCE_TERMINAL`,
  `RE_TERMINAL_BOUNDARY`, `RE_SEPARATOR_RUN`, `RE_SEPARATOR_LINE`,
  `RE_FILL_IN_RUN`, `RE_TRAILING_FILL_IN`, `RE_WHITESPACE`, `RE_NON_ALNUM`,
  `RE_STRUCTURAL_SGML`, `PAGE_NUMBER_CORE`, `CONTINUATION_PUNCTUATION`.

## Command surface

None. There is no `__main__.py` and no entry point. Every symbol is imported by a
higher layer.

## Tests

- [`tests/foundation/text/test_automaton.py`](../../../tests/foundation/text/test_automaton.py)
- [`tests/foundation/text/test_evidence.py`](../../../tests/foundation/text/test_evidence.py)
- [`tests/foundation/text/test_compounds.py`](../../../tests/foundation/text/test_compounds.py)
- [`tests/foundation/text/test_dates.py`](../../../tests/foundation/text/test_dates.py)
- [`tests/foundation/text/test_grammar.py`](../../../tests/foundation/text/test_grammar.py)
- [`tests/foundation/text/test_healing.py`](../../../tests/foundation/text/test_healing.py)
- [`tests/foundation/text/test_normalize.py`](../../../tests/foundation/text/test_normalize.py)
- [`tests/foundation/text/test_patterns.py`](../../../tests/foundation/text/test_patterns.py)
- [`tests/foundation/text/test_tokens.py`](../../../tests/foundation/text/test_tokens.py)

The two scanners that keep this package authoritative are tested at
[`tests/foundation/scanners/test_date_patterns.py`](../../../tests/foundation/scanners/test_date_patterns.py)
and
[`tests/foundation/scanners/test_regex_alternations.py`](../../../tests/foundation/scanners/test_regex_alternations.py).

## Deliberate gaps

- **The tiered bag-of-words engine landed with its classification half
  substituted.** v1 carried `.v1/defs/text/bow/` with per-tier compiled token
  indexes and windowed matching. `compile_lexical_matcher()` now assigns every
  phrase the single tier `("primary", (3, 1, False))`, because the multi-tier
  machinery bought precision no v2 caller used. The *evidence-pack* half could
  not be substituted — `engine/forms/cover/rules.py` compiles a cover's body
  vocabulary into a scored pack and `cover/boundary/corridor.py` reads the 0-3
  score to accept or reject a body root — so it lives in `evidence.py`, sharing
  `tokenize`, `Token`, and `CaseMode` with `automaton.py`. The two halves keep
  separate confidence functions: `automaton.tier_confidence()` rounds to four
  decimals, `evidence.tier_confidence()` does not, because `BowScore.confidence`
  is a calibration output rather than a report value.
- **`MatchPayload.min_distinct_hits` is written and never read by `classify()`.**
  `compile_family_automaton()` propagates the tier's value; `classify()` takes
  its minimum-distinct requirement from `LexicalMatcher.tier_requirements`
  instead, with a `(2, 1, False)` default for an unregistered tier. Setting it on
  a payload has no effect on classification.
- **`ClassificationMatch.exclusion_terms` is always empty.**
  `classify()` computes each category's exclusion terms and skips the category on
  a hit, but `best_excl_hits` is initialised to `()` and never reassigned. The
  field is advertised by the data model; nothing populates it.
- **`CaseMode` is a declaration, not a mechanism.** The `StrEnum` is exported,
  but the automaton compares the raw strings `"exact"` and `"lowercase"` at match
  time and never references the enum. Use the string values.
- **No stemming, lemmatisation, or fuzzy matching.** `expand_variants()` is four
  plural rules and an `-or`/`-our` swap. `derivative` and `derivatives` match only
  because the caller expanded the list.
- **No per-document parallelism.** The automaton is a single-threaded data
  structure; nothing here parallelises a scan.
- **No word-frequency or TF-IDF machinery.** The package produces matches and a
  confidence score; it does not count term frequencies across a corpus.
- **Not ported from v1, by design.** `LogicalUnit` classification has no home in
  `foundation/text/`, and the `.v1/defs/text/reflow/tools/` analysis and
  clustering suites were not ported to any layer — `grep -r cluster
  edgar_sec/engine/reflow/` is empty. Where the rest survived it moved up a
  layer: soft-wrap joining is here in `healing.py`, while checkbox and Yes/No
  rewriting is `engine/forms/cover/healing/`, HTML is `engine/document/html/`,
  whitespace compaction is `engine/document/whitespace/`, table geometry and
  rendering are `engine/tables/ascii_html/`, and `LogicalUnit` /
  `classify_units` live in `engine/document/page_markers/units.py`. Those are
  Layer 3 concerns by design: the document pipeline is not a shared utility.