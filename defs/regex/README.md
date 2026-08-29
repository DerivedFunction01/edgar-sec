# defs/regex — Hierarchical Regex Assembly, Trie Optimization, and Lookaround Safety

Domain-neutral, reusable regular expression builder infrastructure for assembling structured, multi-term, and nested regular expressions with automatic longest-first disambiguation and Python `re` lookbehind safety.

---

## 1. Overview

Regular expressions across pipeline ingestion, dataset viewing, policy enforcement, and financial fact extraction frequently deal with complex keyword alternations and multi-word phrases (e.g., `"interest rate swap"`, `"foreign currency exchange rate derivative contract"`). 

Hand-crafting raw regex strings leads to common pitfalls:
- **Prefix Shadowing**: In standard regex engines, `"swap|interest rate swap"` matches `"swap"` early, missing the longer multi-word phrase.
- **Python `re` Fixed-Width Lookbehind Errors**: Python's standard `re` engine raises `re.error: look-behind requires fixed-width pattern` if variable-length alternatives are combined inside `(?<!...)`.
- **Brittle Boilerplate**: Long lists of tokens (state codes, prohibited statement verbs, derivative types) become unreadable and difficult to extend.
- **Engine Backtracking**: Long alternation lists with shared prefixes cause exponential backtracking without common prefix factorization.

The `defs.regex` module solves these challenges with composable, type-safe builder primitives.

---

## 2. Core API Surface

### `build_alternation(items, sort_longest_first=True, auto_escape=False, compact=False)`
Builds a non-capturing regex alternation `(?:...)` from strings, Enums, or arbitrarily nested sequences.
- **`sort_longest_first=True` (Default)**: Automatically sorts candidates by `(word_count DESC, char_length DESC)` to enforce Max Munch matching.
- **`auto_escape=True`**: Safely escapes regex metacharacters in literal keyword lists.
- **`compact=True`**: Factors common prefixes using a prefix trie.

```python
from defs.regex import build_alternation

# Automatically orders longer multi-word phrases first
pattern = build_alternation(["swap", "interest rate swap", "swap agreement"])
# Result: '(?:interest rate swap|swap agreement|swap)'
```

### `add_restrictions(base, lookaheads=None, lookbehinds=None, lookahead_sep="[- ]", lookbehind_sep="[- ]")`
Wraps a base regex with lookaround assertions.
- **Lookbehind Safety**: Automatically splits variable-length lookbehind terms into individual fixed-width assertions (e.g., `(?<!crypto[- ])(?<!digital[- ])`), preventing Python `re` fixed-width compilation errors.
- **Lookahead Flexibility**: Groups lookaheads into a single alternation group `(?![- ](?:agreement|contract))`.

```python
from defs.regex import add_restrictions

# Safe lookbehinds with variable length terms:
currency = add_restrictions("currency", lookbehinds=["crypto", "digital", "virtual"])
# Result: '(?<!virtual[- ])(?<!digital[- ])(?<!crypto[- ])currency'
```

### `build_compound(prefix=None, core=None, suffix=None, sep_prefix="[- ]", sep_suffix="[- ]")`
Combines prefix, core, and suffix structures with customizable token separators and nested alternations.

```python
from defs.regex import build_compound

pattern = build_compound(
    prefix=["fixed", "floating", "cross-currency"],
    core=["swap", "option", "forward"],
    suffix=["agreement", "contract"],
)
```

### `build_regex(keywords, use_sep=True, flags=re.IGNORECASE, sort_longest_first=True)`
Compiles terms into an `re.Pattern` with optional `\b` word boundary wrapping.

```python
from defs.regex import build_regex

rx = build_regex(["drop", "alter", "delete"], use_sep=True)
# Matches 'drop table' but safely ignores 'droplet'
```

### `compact_alternation(words, auto_escape=True)` / `build_prefix_trie(words)`
Trie-based common prefix factorization for very long term lists.

```python
from defs.regex import compact_alternation

compact = compact_alternation(["swap", "swap agreement", "swap option"])
# Result: 'swap(?: (?:agreement|option))?'
```

### `to_verbose_pattern(pattern, comment=None, indent=4, escape_whitespace=True)`
Formats deep nested alternations across multiple indented lines for `re.VERBOSE` readability.

---

## 3. Subsystem Architecture

```text
defs/
  regex/
    __init__.py          # Public API exports
    builder.py           # Core building primitives (build_alternation, build_compound, etc.)
    trie.py              # Prefix-tree optimizer & factorization
    formatting.py        # Verbose pattern formatter and indentation
defs/tests/
  test_regex_builder.py  # Comprehensive contract & edge-case unit tests
```

---

## 4. Repository Scanners & Adoption Rules

To prevent regressions and maintain codebase quality, the `regex-alternations` policy scanner checks modified files for raw multi-branch pipe strings (e.g. `(?:a|b|c|d)`) and advises developers to use `defs.regex.build_alternation` instead.
