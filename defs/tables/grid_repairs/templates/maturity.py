"""Grid template for headerless maturity value groups."""

from __future__ import annotations

from ...patterns import YEAR_TOKEN_RE
from ...tokens import PREFIX_SYMBOLS, PREFIX_TOKENS
from ..base import GridTemplate, SpanGroup


def match_headerless_maturity_groups(
    rows: list[list[str]], header_count: int, span_groups: list[SpanGroup]
) -> list[SpanGroup]:
    """Match multi-row maturity span groups in the body with year labels."""
    matches = [
        group
        for group in span_groups
        if group[0] >= header_count
        and group[1] == 0
        and group[2] - group[1] == 3
        and YEAR_TOKEN_RE.match(group[3])
    ]
    return matches if len(matches) >= 2 else []


def collapse_headerless_maturity_groups(
    rows: list[list[str]],
    header_count: int,
    drop: set[int],
    span_groups: list[SpanGroup],
) -> None:
    """Collapse prefix symbols into numeric values for headerless maturity tables."""
    for body_row in range(header_count, len(rows)):
        if len(rows[body_row]) < 5:
            continue
        prefix = rows[body_row][3].strip()
        value = rows[body_row][4].strip()
        if (prefix in PREFIX_SYMBOLS or prefix in PREFIX_TOKENS) and value:
            rows[body_row][3] = prefix + value
            rows[body_row][4] = ""
    drop.update({4, 5})


HEADERLESS_MATURITY_TEMPLATE = GridTemplate(
    "headerless_maturity_value_group",
    match_headerless_maturity_groups,
    collapse_headerless_maturity_groups,
)

__all__ = [
    "HEADERLESS_MATURITY_TEMPLATE",
    "collapse_headerless_maturity_groups",
    "match_headerless_maturity_groups",
]
