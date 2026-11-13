"""Grouping signatures: two-dimensional structure as scored evidence.

A family's constitutive grid — component columns crossed with movement
rows and balance bookends — detected over the typed table's header zone
and row labels, independent of caption vocabulary.
"""

from __future__ import annotations

from edgar_sec.engine.forms.common.numbers import clean_numeric
from edgar_sec.foundation.text.dates import RE_FULL_DATE

from .normalize import normalize_text
from .typed_rows import TypedTable

_COMPONENTS: dict[str, tuple[str, ...]] = {
    "common_stock": ("common stock", "common shares"),
    "preferred_stock": ("preferred stock", "preferred shares"),
    "apic": (
        "additional paid-in capital",
        "additional paid in capital",
        "paid-in capital",
        "paid in capital",
        "capital in excess of par",
    ),
    "retained": (
        "retained earnings",
        "accumulated deficit",
        "accumulated earnings",
    ),
    "aoci": ("accumulated other comprehensive",),
    "treasury": ("treasury stock", "treasury shares"),
    "nci": ("noncontrolling interest", "non-controlling interest"),
    "total_equity": (
        "total stockholders' equity",
        "total shareholders' equity",
        "total stockholders equity",
        "total shareholders equity",
        "total equity",
        "members' equity",
        "total members' equity",
        "total capital",
    ),
}

_MOVEMENTS: tuple[str, ...] = (
    "net income",
    "net loss",
    "other comprehensive income",
    "other comprehensive loss",
    "comprehensive income",
    "comprehensive loss",
    "dividends",
    "dividend declared",
    "issuance",
    "issued",
    "repurchase",
    "repurchased",
    "stock-based compensation",
    "share-based compensation",
    "stock compensation",
    "share based compensation",
    "cumulative effect",
    "effect of adoption",
    "adoption of",
    "distributions",
    "contributions",
    "exercise of",
    "exercised",
    "forfeitures",
    "forfeited",
    "vesting",
    "conversion",
    "converted",
    "reclassification",
    "deemed dividend",
    "accretion",
    "shares issued",
    "stock issued",
    "restricted stock",
    "tax benefit",
    "employee stock purchase",
)

_BEGIN_PHRASES: tuple[str, ...] = (
    "beginning balance",
    "balance at beginning",
    "balance at the beginning",
    "balance, beginning",
    "beginning of period",
    "beginning of the period",
    "beginning of year",
    "beginning of the year",
    "balance at january 1",
)
_END_PHRASES: tuple[str, ...] = (
    "ending balance",
    "balance at end",
    "balance at the end",
    "balance, end",
    "end of period",
    "end of the period",
    "end of year",
    "end of the year",
)
_MAX_HEADER_TEXT = 80

COMPONENT_COLUMNS = "component_columns"
ROLLOFFORWARD_GRID = "rollforward_grid"
MOVEMENT_GRID = "movement_grid"
COMPLETE_GRID = "complete_grid"


def _header_zone(table: TypedTable) -> tuple[tuple[str, ...], ...]:
    start = table.caption.consumed_rows
    return table.context.rows[start : start + table.header_rows + 2]


def _label_window(table: TypedTable) -> tuple[tuple[str, ...], ...]:
    start = table.caption.consumed_rows
    return table.context.rows[start : start + table.header_rows + 3]


def header_components(table: TypedTable) -> frozenset[str]:
    """Equity component names heading value columns.

    Header cells wrap across rows, so a component may live in one cell or
    in a column's stacked cells joined; both forms are matched.
    """
    zone = _header_zone(table)
    texts: list[str] = []
    width = max((len(row) for row in zone), default=0)
    for row in zone:
        texts.extend(normalize_text(cell) for cell in row)
    for column in range(width):
        joined = " ".join(
            normalize_text(row[column])
            for row in zone
            if column < len(row) and normalize_text(row[column])
        )
        if joined:
            texts.append(joined)
    found: set[str] = set()
    for text in texts:
        if not text or len(text) > _MAX_HEADER_TEXT:
            continue
        if clean_numeric(text) is not None:
            continue
        if "in thousands" in text or "in millions" in text:
            continue
        for name, phrases in _COMPONENTS.items():
            if any(phrase in text for phrase in phrases):
                found.add(name)
    return frozenset(found)


def _labels(table: TypedTable) -> list[str]:
    labels = [normalize_text(row.label) for row in table.rows]
    labels.extend(normalize_text(row[0]) for row in _label_window(table) if row)
    return [label for label in labels if label]


def movement_row_count(table: TypedTable) -> int:
    """Body rows naming an equity movement (issue, dividend, income...)."""
    return sum(
        1 for label in _labels(table) if any(phrase in label for phrase in _MOVEMENTS)
    )


def has_balance_pair(table: TypedTable) -> bool:
    """Beginning and ending balance rows, worded or dated."""
    texts = [
        label
        for label in _labels(table)
        if "balance" in label
        and (
            any(phrase in label for phrase in _BEGIN_PHRASES)
            or any(phrase in label for phrase in _END_PHRASES)
            or RE_FULL_DATE.search(label)
        )
    ]
    if len(texts) < 2:
        return False
    if any(phrase in text for text in texts for phrase in _BEGIN_PHRASES) and any(
        phrase in text for text in texts for phrase in _END_PHRASES
    ):
        return True
    return sum(1 for text in texts if RE_FULL_DATE.search(text)) >= 2


def grouping_signatures(table: TypedTable) -> frozenset[str]:
    """The grouping signature names this table's grid carries."""
    components = header_components(table)
    fired: set[str] = set()
    if len(components) >= 3:
        fired.add(COMPONENT_COLUMNS)
        if has_balance_pair(table):
            fired.add(ROLLOFFORWARD_GRID)
            if "total_equity" in components and not table.continued:
                fired.add(COMPLETE_GRID)
    if len(components) >= 2 and movement_row_count(table) >= 4:
        fired.add(MOVEMENT_GRID)
    return frozenset(fired)
