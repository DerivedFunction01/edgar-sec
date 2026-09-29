# `edgar_sec/foundation/regex` — the regex builder DSL and prefix-tree factorisation

This package owns how regular expressions are assembled in this repository. It
exists so that no module hand-writes a three-or-more-branch alternation, which is
the spelling that silently loses the longest match and, inside a lookbehind,
fails to compile in Python's `re` engine. It is not a text-extraction package:
it produces pattern strings and compiled patterns, and knows nothing about SEC
filings.

## Purpose

Hand-written alternations have two failure modes that are invisible until they
are not. The first is prefix shadowing: in `(?:swap|interest rate swap)` the
engine matches `swap` and never reaches the longer phrase. The second is Python's
fixed-width lookbehind requirement: a variable-length alternation inside
`(?<!...)` raises `re.error` at compile time.

`builder.py` answers both. `build_alternation()` orders branches
longest-first, and `add_restrictions()` emits one fixed-width assertion per
lookbehind term instead of one alternation group. `trie.py` factors shared
prefixes so a long term list collapses into a compact factored form.

What this package is not: a regex engine, a pattern cache, a validator, or a
text matcher. It does not match text; it builds the string that someone else
compiles.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `builder.py` | Alternation, compound, lookaround, and compiled-pattern construction (209 loc). |
| `trie.py` | Character prefix trie and its regex emission (99 loc). |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

`builder.py` imports `compact_alternation` from `trie.py`
(`builder.py:9`). The dependency does not run the other way: `trie.py` imports
nothing from this repository.

## Contracts

**Guarantees this package makes to its callers**

- `build_alternation(items, sort_longest_first=True, ...)` orders branches by
  `(-len(x.split()), -len(x))` — word count descending, then character length
  descending — before joining them (`builder.py:78-84`). A longer phrase is
  therefore always tried before a shorter one that prefixes it.
- Deduplication happens before sorting, and it preserves first-seen order
  (`builder.py:60-66`), so two identical inputs always produce byte-identical
  output.
- Empty input returns `""`, or `r"(?!)"` when `never_match_empty=True`
  (`builder.py:47`). A never-matching pattern is emitted rather than an empty
  pattern, which would otherwise match everywhere it is interpolated.
- A single-item input returns that item's body, not a one-branch group
  (`builder.py:48-58`).
- `add_restrictions()` builds lookbehinds as repeated separate assertions, one
  per term: `for lb in to_list(lookbehinds): pattern = f"(?<!{lb}{lookbehind_sep}){pattern}"`
  (`builder.py:131-133`). Each assertion is separately fixed-width, so
  variable-length terms never appear inside one lookbehind. Lookaheads are
  grouped into a single alternation, which is safe because a lookahead has no
  width constraint.
- `to_list()` flattens nested lists, tuples, sets, `Enum` members (taking
  `.value`), and bare strings, and returns `[]` for `None`.
- `build_regex(keywords, use_sep=True, flags=re.IGNORECASE, ...)` wraps the
  alternation in `\b...\b` when the built pattern is non-empty
  (`builder.py:190`), then compiles it.
- `compact_alternation()` deduplicates its input, builds the trie, and always
  returns a `(?:...)`-delimited pattern or the single escaped term
  (`trie.py:72-91`).
- `trie_to_regex()` escapes each character by default and collapses a node's
  single-character branches into a character class where every branch is one
  character or one escaped character (`trie.py:57-59`).

**Obligations callers place on this package**

- Escape literal terms. `auto_escape=False` is the default in `builder.py` and
  `True` is the default in `trie.py`; a caller that mixes the two in one
  composition must be deliberate about it.
- Pass raw regex fragments, not literal prose, whenever `auto_escape=False` is
  used. `dates.py` and `grammar.py` depend on this: they pass fragments such as
  `[ivxlcdm]+` and `\d{1,3}` through the DSL unescaped.
- `add_restrictions()` places negative lookbehind *before* the base and negative
  lookahead *after* it. It does not validate that a base pattern is anchored or
  non-empty.
- `add_restrictions()` calls `to_build_alternation(base)` only when `base` is a
  list, tuple, or set; a plain string base is used verbatim after `str(base or "")`
  (`builder.py:125-129`).

## Public surface

- `build_alternation` — non-capturing alternation from strings, enums, or nested sequences, with `sort_longest_first`, `auto_escape`, `compact`, `flexible_whitespace`, and `never_match_empty`. `builder.py`.
- `to_build_alternation` — thin wrapper over `build_alternation` that short-circuits falsy input. `builder.py`.
- `add_restrictions` — wrap a base pattern with negative and positive lookbehind and lookahead assertions, each with its own separator. `builder.py`.
- `build_compound` — concatenate `prefix + sep_prefix + core + sep_suffix + suffix`, expanding each slot as an alternation when it is a collection. `builder.py`.
- `build_regex` — compile an alternation into an `re.Pattern`, optionally `\b`-wrapped. `builder.py`.
- `to_list` — recursive flattening of nested collections, enums, and strings into `list[str]`. `builder.py`.
- `plural` — strip a trailing `?` from a string or `Enum`, normalising plural query marks. `builder.py`.
- `TrieNode` — slotted character-trie node with `children: dict[str, TrieNode]` and `is_end: bool`. `trie.py`.
- `build_prefix_trie` — build a trie from words or phrases, skipping empty strings. `trie.py`.
- `trie_to_regex` — emit a factored regex from a trie node; documented example: `['swap', 'swap agreement', 'swap option']` yields `swap(?: (?:agreement|option))?`. `trie.py`.
- `compact_alternation` — deduplicate, factor through a trie, and wrap in `(?:...)`. `trie.py`.

## Tests

- `tests/foundation/regex/test_builder.py`
- `tests/foundation/regex/test_trie.py`

The scanner that keeps this package load-bearing is
`tests/foundation/scanners/test_regex_alternations.py`, which asserts the
`regex-alternations` scanner's verdict against synthetic violations.

## Deliberate gaps

- **`to_verbose_pattern` and `formatting.py` were not ported.** The v1 package
  `.v1/defs/regex/` carried a `formatting.py` with `to_verbose_pattern(pattern,
  comment=None, indent=4, escape_whitespace=True)`, which re-flowed deep
  alternations across indented lines for readability under `re.VERBOSE`. That
  module and function have no v2 counterpart; this package is `builder.py` and
  `trie.py` only. The alternative is single-line pattern strings. Nothing in v2
  compiles with `re.VERBOSE`.
- **`__init__.py` re-exports nothing.** `from edgar_sec.foundation.regex import
  build_alternation` fails by design; AGENTS.md §1.2 requires importing from
  the leaf module, `from edgar_sec.foundation.regex.builder import
  build_alternation`. The v1 README documented a `defs.regex` facade that no
  longer exists.
- **No pattern caching, timeout, or backtracking guard.** Built patterns are
  plain `str` and `re.Pattern` values. A pathological pattern can still
  backtrack; nothing here detects or bounds that.
- **No engine abstraction.** Output targets Python `re` only. There is no RE2
  or `regex`-module escape hatch, and no attempt is made to emit patterns that
  would be safe under a non-backtracking engine.
- **No pattern validation.** Nothing compiles a built pattern to check it
  before it is returned. `add_restrictions()` can still produce a pattern that
  `re.compile` rejects if a caller passes a bad separator or fragment; the
  failure surfaces at the caller's compile site, not here.
- **No quantified-repetition or capture-group DSL.** `build_compound` models
  prefix/core/suffix with separators only. There is no builder for capturing
  groups, backreferences, conditional patterns, or repetition bounds; those must
  be written literally and are outside the scanner's 3-branch rule.
- **`build_compound` is not a general tree builder.** It is flat — three named
  slots, one separator each. Deeply nested compounds are composed by calling it
  recursively, which is why `regex_alternations.py` and `json_io.py` style
  consumers in `scanners/` nest it inside `build_alternation` by hand.
