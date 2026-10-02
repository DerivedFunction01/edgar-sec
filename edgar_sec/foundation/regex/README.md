# `edgar_sec/foundation/regex` — the regex builder DSL and prefix-tree factorisation

Pattern assembly for the whole repository. No module hand-writes a three-or-more
branch alternation: that spelling loses the longest match, and inside a lookbehind
it fails to compile in Python's `re` engine. This package produces pattern
strings and compiled patterns; it never matches text and knows nothing about SEC
filings.

## Layout

| Module | Responsibility |
| :--- | :--- |
| [`builder.py`](builder.py) | Alternation, compound, lookaround, and compiled-pattern construction. |
| [`trie.py`](trie.py) | Character prefix trie and its factored regex emission. |
| `__init__.py` | One-line docstring. No re-exports, per AGENTS.md §1.2. |

`builder.py` imports `compact_alternation` from `trie.py`. The dependency does
not run the other way.

## Contracts

- `build_alternation()` dedupes first (preserving first-seen order), then sorts
  by `(-word_count, -char_length)` before joining, so a longer phrase is always
  tried before a shorter one that prefixes it. Two identical inputs therefore
  produce byte-identical output.
- Empty input returns `""`, or `r"(?!)"` under `never_match_empty=True`. A
  single item returns its body rather than a one-branch group.
- `add_restrictions()` emits **one separate fixed-width assertion per lookbehind
  term** rather than one alternation group, so a variable-length term never lands
  inside a single lookbehind. Lookaheads are grouped into one alternation, which
  is safe because a lookahead has no width constraint.
- `trie_to_regex()` collapses a node's single-character branches into a character
  class. `['swap', 'swap agreement', 'swap option']` factors to
  `swap(?:\ (?:agreement|option))?`.
- `compact_alternation()` dedupes, builds the trie, and returns a
  `(?:...)`-delimited pattern or the single escaped term.

**Obligations on callers**

- `auto_escape` defaults to `False` in `builder.py` and `True` in `trie.py`. Mix
  them deliberately.
- With `auto_escape=False`, pass raw regex fragments (`[ivxlcdm]+`, `\d{1,3}`),
  not prose.
- `add_restrictions()` calls `to_build_alternation(base)` only for a list, tuple,
  or set; a string base is used verbatim. It does not validate that the base is
  anchored or non-empty.

## Public surface

Import from the leaf module; there is no barrel re-export.

- [`builder.py`](builder.py): `build_alternation`, `to_build_alternation`,
  `add_restrictions`, `build_compound`, `build_regex`, `to_list`, `plural`.
- [`trie.py`](trie.py): `TrieNode`, `build_prefix_trie`, `trie_to_regex`,
  `compact_alternation`.

## Command surface

None. No `__main__.py`, no entry point.

## Tests

- [`tests/foundation/regex/test_builder.py`](../../../tests/foundation/regex/test_builder.py)
- [`tests/foundation/regex/test_trie.py`](../../../tests/foundation/regex/test_trie.py)

The `regex-alternations` scanner's own verdict is pinned at
[`tests/foundation/scanners/test_regex_alternations.py`](../../../tests/foundation/scanners/test_regex_alternations.py).

## Deliberate gaps

- **No `to_verbose_pattern`.** v1's `defs/regex/formatting.py`, which re-flowed
  deep alternations across indented lines for `re.VERBOSE`, was not ported. The
  alternative is single-line pattern strings; nothing here compiles with
  `re.VERBOSE`.
- **No pattern caching, timeout, or backtracking guard.** Output is a plain `str`
  or `re.Pattern`. A pathological pattern can still backtrack.
- **No engine abstraction.** Output targets Python `re` only; there is no RE2 or
  `regex`-module escape hatch.
- **No pattern validation.** Nothing compiles a built pattern to check it. A bad
  separator or fragment surfaces as a `re.error` at the caller's compile site.
- **No quantified-repetition or capture-group DSL.** `build_compound` models
  prefix/core/suffix with separators only; groups, backreferences, conditionals,
  and repetition bounds must be written literally.
- **`build_compound` is flat** — three named slots, one separator each. Nested
  compounds are composed by calling it recursively.