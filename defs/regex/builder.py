"""Composable, hierarchical regex builders with nested alternation and lookaround support."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from .trie import compact_alternation


def to_list(items: Any) -> list[str]:
    """Recursively flatten nested lists, tuples, sets, Enums, and strings to list[str]."""
    if items is None:
        return []
    if isinstance(items, str):
        return [items]
    if isinstance(items, Enum):
        return [str(items.value)]
    if not isinstance(items, (list, tuple, set)):
        return [str(items)]

    out: list[str] = []
    for item in items:
        if isinstance(item, (list, tuple, set)):
            out.extend(to_list(item))
        elif isinstance(item, Enum):
            out.append(str(item.value))
        elif item is not None:
            out.append(str(item))
    return out


def build_alternation(
    items: Any,
    sort_longest_first: bool = True,
    auto_escape: bool = False,
    compact: bool = False,
) -> str:
    """Build a non-capturing regex alternation pattern from strings, enums, or nested sequences.

    Ensures longer, more specific patterns match before shorter prefixes (e.g.,
    'interest rate swap' before 'swap') to prevent prefix shadowing.

    Args:
        items: Term(s), nested sequences, or sub-patterns.
        sort_longest_first: If True, sort by (word_count DESC, char_length DESC).
        auto_escape: If True, escapes regex metacharacters in literal strings.
        compact: If True, factors common prefixes using a trie.

    Returns:
        Alternation pattern string ready for compilation.
    """
    flat = to_list(items)
    if not flat:
        return ""
    if len(flat) == 1:
        val = flat[0]
        if auto_escape:
            val = re.escape(val)
        return val

    # Deduplicate while preserving order for deterministic tiebreakers
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in flat:
        if item not in seen:
            unique_items.append(item)
            seen.add(item)

    if compact:
        return compact_alternation(unique_items, auto_escape=auto_escape)

    if sort_longest_first:
        unique_items.sort(
            key=lambda x: (
                -len(x.split()),  # Primary: word count (descending)
                -len(x),  # Secondary: character length (descending)
            )
        )

    if auto_escape:
        unique_items = [re.escape(x) for x in unique_items]

    return f"(?:{'|'.join(unique_items)})"


def to_build_alternation(
    items: Any, sort_longest_first: bool = True, auto_escape: bool = False
) -> str:
    """Convenience wrapper around build_alternation."""
    if not items:
        return ""
    return build_alternation(
        items, sort_longest_first=sort_longest_first, auto_escape=auto_escape
    )


def add_restrictions(
    base: Any,
    lookaheads: Any = None,
    lookbehinds: Any = None,
    lookahead_sep: str = "[- ]",
    lookbehind_sep: str = "[- ]",
    positive_lookaheads: Any = None,
    positive_lookbehinds: Any = None,
) -> str:
    """Wrap a base regex with lookaround assertions.

    Negative and positive lookbehinds are applied as individual assertions
    to preserve Python's standard `re` fixed-width lookbehind constraint.

    Negative and positive lookaheads support variable-length grouped alternations.
    """
    pattern = (
        to_build_alternation(base)
        if isinstance(base, (list, tuple, set))
        else str(base or "")
    )

    # Negative lookbehinds (split individually to avoid variable-width error)
    if lookbehinds:
        for lb in to_list(lookbehinds):
            pattern = f"(?<!{lb}{lookbehind_sep}){pattern}"

    # Positive lookbehinds
    if positive_lookbehinds:
        for plb in to_list(positive_lookbehinds):
            pattern = f"(?<={plb}{lookbehind_sep}){pattern}"

    # Negative lookaheads
    if lookaheads:
        la_pattern = build_alternation(lookaheads)
        pattern = f"{pattern}(?!{lookahead_sep}{la_pattern})"

    # Positive lookaheads
    if positive_lookaheads:
        pla_pattern = build_alternation(positive_lookaheads)
        pattern = f"{pattern}(?={lookahead_sep}{pla_pattern})"

    return pattern


def build_compound(
    prefix: Any = None,
    core: Any = None,
    suffix: Any = None,
    sep_prefix: str = "[- ]",
    sep_suffix: str = "[- ]",
    sort_longest_first: bool = True,
    auto_escape: bool = False,
) -> str:
    """Build compound term (prefix + core + suffix) with separators and nested alternations."""
    prefix_str = to_build_alternation(
        prefix, sort_longest_first=sort_longest_first, auto_escape=auto_escape
    )
    core_str = to_build_alternation(
        core, sort_longest_first=sort_longest_first, auto_escape=auto_escape
    )
    suffix_str = to_build_alternation(
        suffix, sort_longest_first=sort_longest_first, auto_escape=auto_escape
    )

    prefix_part = f"{prefix_str}{sep_prefix}" if prefix_str else ""
    suffix_part = f"{sep_suffix}{suffix_str}" if suffix_str else ""
    return f"{prefix_part}{core_str}{suffix_part}"


def build_regex(
    keywords: Any,
    use_sep: bool = True,
    flags: re.RegexFlag = re.IGNORECASE,
    sort_longest_first: bool = True,
    auto_escape: bool = False,
    compact: bool = False,
) -> re.Pattern[str]:
    """Build and compile a regex pattern with optional word boundary wrapping."""
    pattern = build_alternation(
        keywords,
        sort_longest_first=sort_longest_first,
        auto_escape=auto_escape,
        compact=compact,
    )
    full_pattern = rf"\b{pattern}\b" if use_sep and pattern else pattern
    return re.compile(full_pattern, flags)


def plural(string: str | Enum) -> str:
    """Normalize plural trailing query marks."""
    if isinstance(string, Enum):
        string = str(string.value)
    return str(string).removesuffix("?")


__all__ = [
    "add_restrictions",
    "build_alternation",
    "build_compound",
    "build_regex",
    "plural",
    "to_build_alternation",
    "to_list",
]
