"""Grid templates for year-group and repeated-value-group span collapsing."""

from __future__ import annotations

from ...patterns import YEAR_IN_HEADER_RE, YEAR_TOKEN_RE
from ...tokens import PREFIX_SYMBOLS, PREFIX_TOKENS, is_numeric_cell
from ..base import GridTemplate, SpanGroup


def collapse_span_groups(
    rows: list[list[str]],
    header_count: int,
    drop: set[int],
    span_groups: list[SpanGroup],
) -> None:
    """Merge 3-column span group values in body rows and mark extra columns for dropping."""
    for row, start, end, label in span_groups:
        if row >= header_count or end - start != 3:
            continue
        if not any(
            any(
                (value in PREFIX_SYMBOLS or value in PREFIX_TOKENS)
                and is_numeric_cell(values[index + 1])
                for index, value in enumerate(values[:-1])
            )
            for body_row in rows[header_count:]
            for values in [[body_row[column].strip() for column in range(start, end)]]
        ):
            continue
        for body_row in range(header_count, len(rows)):
            values = [rows[body_row][column].strip() for column in range(start, end)]
            non_empty = [value for value in values if value]
            if not non_empty:
                continue
            merged = "".join(non_empty)
            rows[body_row][start] = merged
            for column in range(start + 1, end):
                rows[body_row][column] = ""
        drop.update(range(start + 1, end))


def match_year_value_groups(
    rows: list[list[str]], header_count: int, span_groups: list[SpanGroup]
) -> list[SpanGroup]:
    """Match span groups containing year markers in the header."""
    matches = []
    for row, start, end, label in span_groups:
        if row >= header_count or end - start != 3:
            continue
        if not (YEAR_TOKEN_RE.match(label) or YEAR_IN_HEADER_RE.search(label)):
            continue
        if any(
            any(
                (value in PREFIX_SYMBOLS or value in PREFIX_TOKENS)
                and is_numeric_cell(values[index + 1])
                for index, value in enumerate(values[:-1])
            )
            for values in (
                [rows[body_row][column].strip() for column in range(start, end)]
                for body_row in range(header_count, len(rows))
            )
        ):
            matches.append((row, start, end, label))
    return matches


def match_repeated_value_groups(
    rows: list[list[str]], header_count: int, span_groups: list[SpanGroup]
) -> list[SpanGroup]:
    """Match repeated non-year span groups with currency/spacer body patterns."""
    candidates = []
    for group in span_groups:
        row, start, end, label = group
        if row >= header_count or end - start != 3 or not label.strip():
            continue
        if YEAR_TOKEN_RE.match(label) or YEAR_IN_HEADER_RE.search(label):
            continue
        if any(
            any(
                (value in PREFIX_SYMBOLS or value in PREFIX_TOKENS)
                and is_numeric_cell(values[index + 1])
                for index, value in enumerate(values[:-1])
            )
            for body_row in range(header_count, len(rows))
            for values in [
                [rows[body_row][column].strip() for column in range(start, end)]
            ]
        ):
            candidates.append(group)
    return candidates if len(candidates) >= 2 else []


YEAR_VALUE_GROUP_TEMPLATE = GridTemplate(
    "year_group_currency_value_spacer",
    match_year_value_groups,
    collapse_span_groups,
)

REPEATED_VALUE_GROUP_TEMPLATE = GridTemplate(
    "repeated_value_group_currency_spacer",
    match_repeated_value_groups,
    collapse_span_groups,
)

__all__ = [
    "REPEATED_VALUE_GROUP_TEMPLATE",
    "YEAR_VALUE_GROUP_TEMPLATE",
    "collapse_span_groups",
    "match_repeated_value_groups",
    "match_year_value_groups",
]
