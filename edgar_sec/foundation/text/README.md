# `edgar_sec/foundation/text` — shared text vocabulary

Pattern vocabulary more than one layer needs: month tables and the ordered SEC
date formats, bullet and roman-numeral tokens, the English closed-class word
lists, Unicode whitespace normalisation, Cartesian phrase generation, soft-wrap
line healing, and token-level matching. It does not parse documents and knows
nothing about filings.

## Contracts

- **Date parsing**: `parse_date()` returns `None` on unparseable input rather than raising, skips a format whose pattern matched only partially, and rejects a year outside `YEAR_RANGE`.
- **Tokenization**: `tokenize()` maps dash characters to a space before matching, so `Token.start` and `Token.end` index the *translated* string, not the caller's original text.
- **Classification exclusions**: `classify()` skips a category entirely if any of its exclusion terms hit. Exclusions are not subtractive.
- **Compound expansion**: `expand_compounds(*slots)` treats a `None` slot, or a collection containing `None` or `""`, as optional and drops the empty combination rather than yielding a double separator.
- **Roman numerals**: `roman_to_int()` accepts only a canonical bounded Roman numeral; a total whose re-encoding does not match the input returns `None`.

**Obligations on callers**

- **No private tables**: Do not define a private month table, inline month sequence, hand-written month alternation, or hand-written date separator pattern.
- **Use builder DSL**: Do not write a raw multi-branch alternation here expecting exemption from the scanner's *intent*. Use `build_alternation`, `build_compound`, or `compact_alternation`.
- **Offset derivation**: Re-derive source offsets from the original string if you need them; token offsets cannot be mapped back.
- **Regex footgun**: `PhraseSequenceRule` entries that are plain strings pass through the DSL **unescaped** when they contain `|` or start with `\d`. A literal containing regex metacharacters is a footgun.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **Classification through the automaton is single-tier**: `compile_lexical_matcher()` registers one tier for every phrase, so precision cannot be expressed per tier. The scored multi-tier path is a separate mechanism, `compile_evidence_pack()` in `evidence.py`.
- **Two returned fields are inert**: `MatchPayload.min_distinct_hits` has no effect on `classify()`, which takes a tier's minimum-distinct requirement from `LexicalMatcher.tier_requirements`; `ClassificationMatch.exclusion_terms` is always empty, because an exclusion hit disqualifies the category before a match is built.
- **No stemming, lemmatisation, or fuzzy matching**: `expand_variants()` is a plural-rule list and an `-or`/`-our` swap, so `derivative` and `derivatives` match only if the caller expanded both.
- **No corpus statistics and no parallelism**: The package produces matches and a confidence score; it does not count term frequencies, and a scan is single-threaded.
- **Document-structure analysis is not in this layer**: Soft-wrap joining is the only document-level transform here. Checkbox and Yes/No rewriting, HTML, whitespace compaction, table geometry, and logical-unit classification are engine concerns, by design: the document pipeline is not a shared utility, and nothing here clusters or classifies document sections.
