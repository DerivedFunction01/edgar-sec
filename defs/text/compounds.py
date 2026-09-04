"""Domain-neutral Cartesian compound and alternation string builder for string matchers, BoW, and taxonomies."""

from __future__ import annotations

import itertools
import re
from enum import Enum
from typing import Any


def _to_str_list(items: Any) -> list[str]:
    """Recursively flatten nested lists, tuples, sets, Enums, and strings to list[str]."""
    if items is None:
        return []
    if isinstance(items, str):
        cleaned = items.strip()
        return [cleaned] if cleaned else []
    if isinstance(items, Enum):
        cleaned = str(items.value).strip()
        return [cleaned] if cleaned else []
    if not isinstance(items, (list, tuple, set, frozenset)):
        cleaned = str(items).strip()
        return [cleaned] if cleaned else []

    out: list[str] = []
    for item in items:
        if isinstance(item, (list, tuple, set, frozenset)):
            out.extend(_to_str_list(item))
        elif isinstance(item, Enum):
            cleaned = str(item.value).strip()
            if cleaned:
                out.append(cleaned)
        elif item is not None:
            cleaned = str(item).strip()
            if cleaned:
                out.append(cleaned)
    return out


def expand_alternations(
    *items: Any,
    deduplicate: bool = True,
    sort_longest_first: bool = True,
) -> tuple[str, ...]:
    """Flatten and normalize nested terms, enums, and sequences into a tuple of strings.

    Args:
        *items: Strings, Enums, or nested sequences.
        deduplicate: If True, preserves first occurrence of each term.
        sort_longest_first: If True, sorts by word count desc, character length desc.

    Returns:
        Tuple of normalized strings.
    """
    flat: list[str] = []
    for it in items:
        flat.extend(_to_str_list(it))

    if not deduplicate and not sort_longest_first:
        return tuple(flat)

    seen: set[str] = set()
    unique: list[str] = []
    for term in flat:
        norm = re.sub(r"\s+", " ", term).strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(norm)

    if sort_longest_first:
        unique.sort(
            key=lambda x: (
                -len(x.split()),  # Word count descending
                -len(x),  # Character length descending
                x,  # Alphabetical tie-breaker
            )
        )

    return tuple(unique)


def expand_variants(
    base_terms: Any,
    *,
    plurals: bool = True,
    us_uk_spelling: bool = True,
) -> tuple[str, ...]:
    """Expand base terms with regular English plural forms and US/UK spelling variants.

    Args:
        base_terms: Base word(s) or sequence.
        plurals: If True, generates singular and regular plural variants.
        us_uk_spelling: If True, expands common variants like labor/labour.

    Returns:
        Tuple of unique term variants.
    """
    flat = _to_str_list(base_terms)
    expanded: list[str] = []

    for term in flat:
        clean = term.strip().lower()
        if not clean:
            continue
        variants = {clean}

        if us_uk_spelling:
            if clean.endswith("or") and len(clean) > 3:
                variants.add(clean[:-2] + "our")
            elif clean.endswith("our") and len(clean) > 4:
                variants.add(clean[:-3] + "or")
            elif "or" in clean and not clean.startswith("or"):
                variants.add(clean.replace("or", "our"))
            elif "our" in clean:
                variants.add(clean.replace("our", "or"))

        if plurals:
            plural_set: set[str] = set()
            for v in variants:
                if v.endswith(("s", "sh", "ch", "x", "z")):
                    plural_set.add(f"{v}es")
                elif v.endswith("y") and len(v) > 1 and v[-2] not in "aeiou":
                    plural_set.add(f"{v[:-1]}ies")
                elif v.endswith("man"):
                    plural_set.add(f"{v[:-3]}men")
                elif not v.endswith("s"):
                    plural_set.add(f"{v}s")
            variants.update(plural_set)

        expanded.extend(variants)

    return expand_alternations(expanded, deduplicate=True, sort_longest_first=True)


def expand_compounds(
    *slots: Any,
    sep: str = " ",
    sort_longest_first: bool = True,
) -> tuple[str, ...]:
    """Generate Cartesian-product compound phrases from sequential token/phrase slots.

    Each slot can be:
    - A single string or Enum.
    - A sequence of strings / Enums.
    - An optional slot containing ``None`` or ``""`` alongside candidate terms.

    Args:
        *slots: Positional token slots to combine.
        sep: Separator between slots (default: single space).
        sort_longest_first: If True, sort results with longest phrases first.

    Returns:
        Tuple of unique, normalized compound strings.

    Example:
        >>> expand_compounds(["collective", "labor"], ["bargaining", "agreement"])
        ('collective bargaining', 'collective agreement', 'labor bargaining', 'labor agreement')
        >>> expand_compounds(["union"], [None, "pension"], ["plan", "plans"])
        ('union pension plans', 'union pension plan', 'union plans', 'union plan')
    """
    if not slots:
        return ()

    slot_options: list[list[str]] = []
    for slot in slots:
        # Check if slot is optional (contains None or empty string)
        is_optional = False
        if slot is None:
            is_optional = True
            raw_items: list[Any] = []
        elif isinstance(slot, (list, tuple, set, frozenset)):
            is_optional = any(x is None or x == "" for x in slot)
            raw_items = [x for x in slot if x is not None and x != ""]
        else:
            raw_items = [slot]

        cleaned_items = _to_str_list(raw_items)
        options: list[str] = []
        if is_optional:
            options.append("")
        options.extend(cleaned_items)

        if not options:
            continue
        slot_options.append(options)

    if not slot_options:
        return ()

    results: list[str] = []
    for combo in itertools.product(*slot_options):
        # Join non-empty parts with separator
        parts = [p.strip() for p in combo if p.strip()]
        if parts:
            phrase = sep.join(parts)
            results.append(phrase)

    return expand_alternations(
        results, deduplicate=True, sort_longest_first=sort_longest_first
    )


__all__ = [
    "expand_alternations",
    "expand_compounds",
    "expand_variants",
]
