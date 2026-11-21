"""Filed dei period/fiscal metadata read from a filing's own cover facts."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from edgar_sec.engine.xbrl.schema.models import XbrlFact

_FIELDS = frozenset(
    {
        "dei:DocumentPeriodEndDate",
        "dei:DocumentFiscalYearFocus",
        "dei:DocumentFiscalPeriodFocus",
        "dei:DocumentType",
        "dei:DocumentAnnualReport",
        "dei:DocumentQuarterlyReport",
        "dei:DocumentTransitionReport",
        "dei:AmendmentFlag",
    }
)
_FYE_QNAMES = ("dei:CurrentFiscalYearEndDate", "dei:EntityFiscalYearEndDate")
_FOCUS_CLASSES = {"Q1": "QUARTER", "Q2": "YTD_2Q", "Q3": "YTD_3Q", "FY": "ANNUAL"}
_MONTH_DAY = re.compile(r"--(\d{2})-(\d{2})")


@dataclass(frozen=True, slots=True)
class FiledMetadata:
    """A filing's filed dei period/fiscal block; None where unfiled."""

    period_end: str | None = None
    fiscal_year: int | None = None
    period_focus: str | None = None
    document_type: str | None = None
    fiscal_year_end: tuple[int, int] | None = None
    annual_report: bool | None = None
    quarterly_report: bool | None = None
    transition_report: bool | None = None
    amendment: bool | None = None


def _pick(candidates: list[tuple[bool, object]]) -> object:
    """Modal filed value, undimensioned facts preferred over dimensioned."""
    pool = [v for dim, v in candidates if not dim] or [v for _, v in candidates]
    return Counter(pool).most_common(1)[0][0]


def _as_year(value: object) -> int | None:
    """Coerce a filed fiscal-year focus (gYear text or float) to an int."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_bool(value: object) -> bool | None:
    """Coerce a filed boolean (bool or true/false text) to a bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1"):
            return True
        if low in ("false", "0"):
            return False
    return None


def _as_month_day(value: object) -> tuple[int, int] | None:
    """Parse a filed fiscal-year-end (--MM-DD or an ISO date) to (month, day)."""
    if not isinstance(value, str):
        return None
    match = _MONTH_DAY.fullmatch(value.strip())
    if match:
        return int(match.group(1)), int(match.group(2))
    try:
        parsed = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
    return parsed.month, parsed.day


def _as_text(value: object) -> str | None:
    """A filed text value, stripped; None for non-text or empty values."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def filed_metadata(facts: Iterable[XbrlFact]) -> FiledMetadata:
    """Read the dei period/fiscal block from a filing's facts."""
    found: dict[str, list[tuple[bool, object]]] = {}
    for fact in facts:
        if fact.concept_qname in _FIELDS or fact.concept_qname in _FYE_QNAMES:
            found.setdefault(fact.concept_qname, []).append(
                (bool(fact.dimensions), fact.value)
            )

    def pick(qname: str) -> object:
        return _pick(found[qname]) if qname in found else None

    fye_raw = next((pick(q) for q in _FYE_QNAMES if q in found), None)
    return FiledMetadata(
        period_end=_as_text(pick("dei:DocumentPeriodEndDate")),
        fiscal_year=_as_year(pick("dei:DocumentFiscalYearFocus")),
        period_focus=_as_text(pick("dei:DocumentFiscalPeriodFocus")),
        document_type=_as_text(pick("dei:DocumentType")),
        fiscal_year_end=_as_month_day(fye_raw),
        annual_report=_as_bool(pick("dei:DocumentAnnualReport")),
        quarterly_report=_as_bool(pick("dei:DocumentQuarterlyReport")),
        transition_report=_as_bool(pick("dei:DocumentTransitionReport")),
        amendment=_as_bool(pick("dei:AmendmentFlag")),
    )


def fiscal_year_containing(period_end: str, fiscal_year_end: tuple[int, int]) -> int:
    """Fiscal year containing a date, named by its ending calendar year.

    Start-year naming is not span-derivable; the filed focus stays authority.
    """
    end = date.fromisoformat(period_end[:10])
    try:
        fye_this = date(end.year, fiscal_year_end[0], fiscal_year_end[1])
    except ValueError:
        fye_this = date(end.year, fiscal_year_end[0], 28)
    return end.year if end <= fye_this else end.year + 1


def focus_length_class(period_focus: str | None) -> str | None:
    """Length class a filed period focus names; None for unmapped foci."""
    return _FOCUS_CLASSES.get(period_focus or "")
