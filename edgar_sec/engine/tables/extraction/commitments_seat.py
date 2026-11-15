"""Commitments seat: geometry-text claims in MD&A / note regions.

The relocated seat for commitments_contingencies (refresh Step 4):
the claim reads the geometry's own text, seated by the Step 2
context contract, never the note title alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE

from .context_production import SEAT_MDA
from .normalize import normalize_text
from .typed_rows import TypedTable, parse_caption_stack

FAMILY = "commitments_contingencies"
PROV_SEAT = "refresh-step4:commitments-seat"
FORM_PAYMENTS_DUE = "payments_due"
FORM_CREDIT_CLUSTER = "credit_cluster"
FORM_GUARANTEE_SCHEDULE = "guarantee_schedule"
POINTS_PAYMENTS_DUE = 6.0
POINTS_CLUSTER = 5.0

_MDA_TITLE = "management's discussion and analysis"
_PURCHASE_TERMS = ("purchase obligations", "purchase commitments")
_CREDIT_CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("extend_credit", ("commitments to extend credit",)),
    ("unused_lines", ("unused lines of credit", "commitments for unused lines")),
    ("letters_of_credit", ("letters of credit",)),
    ("standby_bond_purchase", ("standby bond purchase",)),
    ("unfunded", ("unfunded commitments",)),
)
_GUARANTEE_TERMS = ("guarantee", "guarantees", "guarantor", "surety")
_FRAMING_TERMS = (
    "commitments",
    "contractual obligations",
    "material cash requirements",
    "commercial commitments",
    "off-balance sheet",
    "outstanding commitments",
)
_BUCKET_TERMS = (
    "less than 1 year",
    "less than one year",
    "within 1 year",
    "1 to 2 years",
    "1 to 3 years",
    "2 to 3 years",
    "3 to 4 years",
    "3 to 5 years",
    "4 to 5 years",
    "more than 5 years",
    "after 5 years",
    "thereafter",
)
_EXPIRY_TERMS = ("expir", "maturit")
_TOTAL_RE = re.compile(r"^\s*total\b")
_MIN_BUCKETS = 3
_MIN_CREDIT_CONCEPTS = 2


@dataclass(frozen=True, slots=True)
class SeatVerdict:
    """The seat's verdict for one table: form, points, region."""

    passed: bool
    form: str | None
    points: float
    region: str | None
    detail: str


_REFUSED = SeatVerdict(False, None, 0.0, None, "")


def seat_region(table: TypedTable) -> str | None:
    """The claim region the Step 2 contract seats this table in."""
    context = table.context
    if context.seat == SEAT_MDA:
        return "mda"
    if context.note is not None:
        return "note"
    if context.seat is not None:
        return None
    section = context.section
    if section is not None and section.title:
        if _MDA_TITLE in normalize_text(section.title):
            return "mda"
    return None


def _header_text(table: TypedTable) -> str:
    rows = table.context.rows
    caption = parse_caption_stack(rows)
    body = rows[caption.consumed_rows :]
    parts: list[str] = [
        period.label for period in table.periods if period.label is not None
    ]
    for row in body:
        parts.extend(cell for cell in row if cell.strip())
    return normalize_text(" ".join(parts))


def _bucket_count(header: str, stub_text: str) -> int:
    text = f"{header} {stub_text}"
    count = sum(1 for term in _BUCKET_TERMS if term in text)
    years = set(YEAR_TOKEN_SEARCH_RE.findall(header))
    if len(years) >= 3:
        count = max(count, len(years))
    return count


def _valued_label(table: TypedTable, needles: tuple[str, ...]) -> str | None:
    for row in table.rows:
        if not any(value is not None for value in row.values):
            continue
        label = normalize_text(row.label)
        if any(needle in label for needle in needles):
            return label
    return None


def evaluate_commitments_seat(table: TypedTable) -> SeatVerdict:
    """Judge one table under the relocated commitments seat."""
    region = seat_region(table)
    if region is None:
        return _REFUSED
    context = table.context
    stubs = [normalize_text(row.label) for row in table.rows]
    stub_text = " ".join(label for label in stubs if label)
    caption = normalize_text(
        " | ".join([*context.caption_stack, *table.caption.titles])
    )
    note_title = normalize_text(context.note.title) if context.note else ""
    framing = f"{caption} {note_title}"
    header = _header_text(table)
    purchase = _valued_label(table, _PURCHASE_TERMS)
    if purchase is not None and _bucket_count(header, stub_text) >= _MIN_BUCKETS:
        return SeatVerdict(
            True,
            FORM_PAYMENTS_DUE,
            POINTS_PAYMENTS_DUE,
            region,
            f"payments-due: {purchase}",
        )
    concepts = tuple(
        name
        for name, terms in _CREDIT_CONCEPTS
        if any(term in stub_text or term in caption for term in terms)
    )
    framed = any(term in framing for term in _FRAMING_TERMS)
    expiry = any(term in header for term in _EXPIRY_TERMS)
    if len(concepts) >= _MIN_CREDIT_CONCEPTS and (framed or expiry):
        return SeatVerdict(
            True,
            FORM_CREDIT_CLUSTER,
            POINTS_CLUSTER,
            region,
            f"credit cluster: {', '.join(concepts)}",
        )
    guarantee = _valued_label(table, _GUARANTEE_TERMS)
    if guarantee is not None and (concepts or purchase is not None):
        return SeatVerdict(
            True,
            FORM_GUARANTEE_SCHEDULE,
            POINTS_CLUSTER,
            region,
            f"guarantee schedule: {guarantee}",
        )
    return SeatVerdict(False, None, 0.0, region, "")
