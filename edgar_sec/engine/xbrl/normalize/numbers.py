"""Compositional number-word grammar for concept token streams.

Cardinal phrases (One..Nineteen, Twenty..Ninety, Hundred/Thousand scales)
and single ordinal words (First..Ninetieth) collapse to one NUM token when
anchored by a unit noun or bucket word; values render as num=/ord= indexicals.
"""

from __future__ import annotations

NUM_TOKEN = "NUM"

_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "thirtieth": 30,
    "fortieth": 40,
    "fiftieth": 50,
    "sixtieth": 60,
    "seventieth": 70,
    "eightieth": 80,
    "ninetieth": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000}
_UNIT_NOUNS = {
    "year",
    "years",
    "month",
    "months",
    "day",
    "days",
    "week",
    "weeks",
    "quarter",
    "quarters",
    "percent",
}
_ANCHOR_PREV = {
    "due",
    "rolling",
    "after",
    "within",
    "through",
    "between",
    "next",
    "tier",
    "level",
}
_RANGE_LINKS = {"through", "to"}


def parse_number_phrase(tokens: tuple[str, ...], start: int) -> tuple[int, int] | None:
    """Parse a cardinal phrase at start, returning (value, next index)."""
    word = tokens[start].lower()
    if word.isdigit():
        return int(word), start + 1
    if word in _TENS:
        value = _TENS[word]
        nxt = start + 1
        if nxt < len(tokens) and _UNITS.get(tokens[nxt].lower(), 99) < 10:
            value += _UNITS[tokens[nxt].lower()]
            nxt += 1
        return value, nxt
    if word not in _UNITS:
        return None
    value = _UNITS[word]
    nxt = start + 1
    if nxt < len(tokens) and tokens[nxt].lower() in _SCALES:
        value *= _SCALES[tokens[nxt].lower()]
        nxt += 1
        if nxt < len(tokens) and tokens[nxt].lower() in _TENS:
            value += _TENS[tokens[nxt].lower()]
            nxt += 1
            if nxt < len(tokens) and _UNITS.get(tokens[nxt].lower(), 99) < 10:
                value += _UNITS[tokens[nxt].lower()]
                nxt += 1
        elif nxt < len(tokens) and tokens[nxt].lower() in _UNITS:
            value += _UNITS[tokens[nxt].lower()]
            nxt += 1
    return value, nxt


def parse_ordinal_phrase(tokens: tuple[str, ...], start: int) -> tuple[int, int] | None:
    """Parse a single ordinal word at start, returning (value, next index)."""
    value = _ORDINALS.get(tokens[start].lower())
    if value is None:
        return None
    return value, start + 1


def _anchored(tokens: tuple[str, ...], start: int, nxt: int) -> bool:
    """True when a phrase at start..nxt sits by a unit noun or bucket word."""
    prev = tokens[start - 1].lower() if start > 0 else ""
    following = tokens[nxt].lower() if nxt < len(tokens) else ""
    return following in _UNIT_NOUNS or prev in _UNIT_NOUNS or prev in _ANCHOR_PREV


def collapse_number_phrases(
    tokens: tuple[str, ...],
) -> tuple[tuple[str, ...], dict[int, int], dict[int, int]]:
    """Collapse anchored phrases to NUM; return (tokens, cardinals, ordinals)."""
    out: list[str] = []
    values: dict[int, int] = {}
    ordinals: dict[int, int] = {}
    i = 0
    while i < len(tokens):
        parsed = parse_number_phrase(tokens, i)
        if (
            parsed is not None
            and not (tokens[i].isdigit() and parsed[1] == len(tokens))
            and _anchored(tokens, i, parsed[1])
        ):
            values[len(out)] = parsed[0]
            out.append(NUM_TOKEN)
            i = parsed[1]
            continue
        ordinal = parse_ordinal_phrase(tokens, i)
        if ordinal is not None and _anchored(tokens, i, ordinal[1]):
            ordinals[len(out)] = ordinal[0]
            out.append(NUM_TOKEN)
            i = ordinal[1]
            continue
        out.append(tokens[i])
        i += 1
    return tuple(out), values, ordinals


def number_indexicals(
    tokens: tuple[str, ...],
    values: dict[int, int],
    ordinals: dict[int, int] | None = None,
) -> tuple[str, ...]:
    """Render values as num=/ord= indexicals, merging same-kind NUM ranges."""
    entries = sorted(
        [(idx, "num", v) for idx, v in values.items()]
        + [(idx, "ord", v) for idx, v in (ordinals or {}).items()]
    )
    rendered: list[str] = []
    pos = 0
    while pos < len(entries):
        idx, kind, value = entries[pos]
        if pos + 1 < len(entries):
            nidx, nkind, nvalue = entries[pos + 1]
            if (
                nkind == kind
                and nidx == idx + 2
                and tokens[idx + 1].lower() in _RANGE_LINKS
            ):
                rendered.append(f"{kind}={value}..{nvalue}")
                pos += 2
                continue
        rendered.append(f"{kind}={value}")
        pos += 1
    return tuple(rendered)
