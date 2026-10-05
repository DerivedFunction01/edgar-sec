# `edgar_sec/foundation/text` — shared text vocabulary

Pattern vocabulary more than one layer needs: month tables and the ordered SEC
date formats, bullet and roman-numeral tokens, the English closed-class word
lists, Unicode whitespace normalisation, Cartesian phrase generation, soft-wrap
line healing, and token-level matching. It does not parse documents and knows
nothing about filings.

## Layout

| Module | Responsibility |
| :--- | :--- |
| [`automaton.py`](automaton.py) | Token-level Aho-Corasick automaton, lexical matcher, evidence-family compilation, classification. |
| [`dates.py`](dates.py) | Month tables, ordered SEC date formats, year expansion and extraction. |
| [`evidence.py`](evidence.py) | Token-boundary lexical evidence packs and the tier scorer. |
| [`compounds.py`](compounds.py) | Cartesian compound phrases, plural and US/UK variants, term normalisation. |
| [`grammar.py`](grammar.py) | English closed-class words and prose grammar patterns. |
| [`healing.py`](healing.py) | Soft-wrap line joining: phrase-sequence rules and boundary guards. |
| [`normalize.py`](normalize.py) | Unicode whitespace sanitisation and blank-line compaction. |
| [`patterns.py`](patterns.py) | Domain-neutral line-shape regexes: leaders, column gaps, separators. |
| [`tokens.py`](tokens.py) | Bullet and ordered markers, footnote marks, Roman numeral conversion. |

`text/` and [`foundation/regex/`](../regex/README.md) are the only path prefixes the
`regex-alternations` scanner exempts: multi-branch alternation vocabulary
legitimately lives here, so build it with the regex DSL rather than by hand.

## Contracts

**Guarantees to callers**

- `parse_date()` returns `None` on unparseable input rather than raising, skips a
  format whose pattern matched only partially, and rejects a year outside
  `YEAR_RANGE`.
- `tokenize()` maps dash characters to a space before matching, so `Token.start`
  and `Token.end` index the *translated* string, not the caller's original text.
- `classify()` skips a category entirely if any of its exclusion terms hit.
  Exclusions are not subtractive.
- `expand_compounds(*slots)` treats a `None` slot, or a collection containing
  `None` or `""`, as optional and drops the empty combination rather than
  yielding a double separator.
- `roman_to_int()` accepts only a canonical bounded Roman numeral; a total whose
  re-encoding does not match the input returns `None`.

**Obligations on callers**

- Do not define a private month table, inline month sequence, hand-written month
  alternation, or hand-written date separator pattern.
- Do not write a raw multi-branch alternation here expecting exemption from the
  scanner's *intent*. Use `build_alternation`, `build_compound`, or
  `compact_alternation`.
- Re-derive source offsets from the original string if you need them; token
  offsets cannot be mapped back.
- `PhraseSequenceRule` entries that are plain strings pass through the DSL
  **unescaped** when they contain `|` or start with `\d`. A literal containing
  regex metacharacters is a footgun.

## Public surface

Import from the leaf module.

- [`dates.py`](dates.py): `parse_date`, `expand_2digit_year`, `extract_years`,
  `SEC_DATE_FORMATS` with its `DateFormat` / `DateComponents` / `ParsedDate`
  records, the `MONTH_*` vocabulary, and the year-range constants.
- [`automaton.py`](automaton.py): `tokenize`, `Token`,
  `MultiPatternAutomaton`, `LexicalMatcher`, `compile_lexical_matcher`,
  `compile_family_automaton`, `MatchPayload`, `ClassificationMatch`,
  `tier_confidence`, `CaseMode`.
- [`evidence.py`](evidence.py): `LexicalEvidencePack`, `EvidenceTier`,
  `EvidenceContext`, `compile_evidence_pack`, `tier_confidence`.
- [`compounds.py`](compounds.py): `expand_alternations`, `expand_variants`,
  `expand_compounds`.
- [`grammar.py`](grammar.py): the closed-class word lists and the prose patterns
  compiled from them.
- [`healing.py`](healing.py): `heal_split_lines`, `should_join_two_lines`,
  `PhraseSequenceRule`.
- [`normalize.py`](normalize.py): `sanitize_unicode_whitespace`,
  `collapse_whitespace`, `collapse_excessive_blank_lines`, `NORMALIZE_TO_SPACE`,
  `STRIP_ZERO_WIDTH`.
- [`tokens.py`](tokens.py): the marker and footnote vocabularies with their
  compiled patterns, `is_list_or_bullet_marker`, `is_bullet_line`,
  `is_ordered_marker_prefix`, `roman_to_int`.
- [`patterns.py`](patterns.py): the domain-neutral line-shape patterns.

## Command surface

None. There is no `__main__.py` and no entry point; every symbol is imported by a
higher layer.

## Mirrored tests

[`tests/foundation/text/`](../../../tests/foundation/text/). The scanners that keep
this package authoritative are tested in
[`tests/foundation/scanners/`](../../../tests/foundation/scanners/).

## Deliberate gaps

- **Classification through the automaton is single-tier.**
  `compile_lexical_matcher()` registers one tier for every phrase, so precision
  cannot be expressed per tier. The scored multi-tier path is a separate
  mechanism, `compile_evidence_pack()` in `evidence.py`.
- **Two returned fields are inert.** `MatchPayload.min_distinct_hits` has no
  effect on `classify()`, which takes a tier's minimum-distinct requirement from
  `LexicalMatcher.tier_requirements`; `ClassificationMatch.exclusion_terms` is
  always empty, because an exclusion hit disqualifies the category before a match
  is built.
- **No stemming, lemmatisation, or fuzzy matching.** `expand_variants()` is a
  plural-rule list and an `-or`/`-our` swap, so `derivative` and `derivatives`
  match only if the caller expanded both.
- **No corpus statistics and no parallelism.** The package produces matches and a
  confidence score; it does not count term frequencies, and a scan is
  single-threaded.
- **Document-structure analysis is not in this layer.** Soft-wrap joining is the
  only document-level transform here. Checkbox and Yes/No rewriting, HTML,
  whitespace compaction, table geometry, and logical-unit classification are
  engine concerns, by design: the document pipeline is not a shared utility, and
  nothing here clusters or classifies document sections.