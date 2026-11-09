"""Company-facts TTM comparison surface for item 19 Step 5.

The landed cross-check-only posture binds: company-facts values are
computed here solely to compare against the XBRL TTM surface; they
never serve anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from edgar_sec.apps.client.companyfacts import (
    AGREE,
    DIVERGE,
    FACTS_ONLY,
    PARSED_ONLY,
    CompanyFacts,
    _current_points,
)
from edgar_sec.apps.client.financials_ttm import (
    _TTM_CLASSES,
    QuarterLegSet,
    SpanLeg,
    TtmResult,
    _discrete_quarters,
    _ttm_window,
)
from edgar_sec.engine.xbrl.normalize.normalization import (
    normalize_time_coordinate,
)
from edgar_sec.engine.xbrl.solve.query import QueryStatus

if TYPE_CHECKING:
    from edgar_sec.pipelines.metadata_sync.facts_store import StoredFact

__all__ = [
    "TtmComparisonRow",
    "compare_ttm",
    "facts_eps_ttm",
    "facts_quarter_legs",
    "facts_ttm",
    "facts_ttm_from_store",
]


def _length_class(start: str, end: str) -> str | None:
    """A facts duration point's length class, the kernel's own rule."""
    return normalize_time_coordinate("duration", None, start, end).length_class


def _unit_points(facts: CompanyFacts, taxonomy: str, tag: str) -> dict[str, list]:
    """Duration facts points for one concept, grouped by unit."""
    by_unit: dict[str, list] = {}
    for point in _current_points(facts).values():
        if point.taxonomy != taxonomy or point.tag != tag:
            continue
        if not point.start:
            continue
        by_unit.setdefault(point.unit, []).append(point)
    return by_unit


def _pick_unit(by_unit: dict[str, list]) -> str:
    """The unit with the most in-window-class points; name breaks ties."""

    def key(unit: str) -> tuple[int, str]:
        count = sum(
            1
            for point in by_unit[unit]
            if _length_class(point.start, point.end) in _TTM_CLASSES
        )
        return (-count, unit)

    return min(by_unit, key=key)


def facts_quarter_legs(
    facts: CompanyFacts,
    taxonomy: str,
    tag: str,
    *,
    unit: str | None = None,
    weighted: bool = False,
) -> QuarterLegSet:
    """Quarter legs over a company-facts document, XBRL-surface shape.

    The document's latest-filed value per point wins; discrete quarters
    derive by the within-filing differencer, reported points winning.
    """
    by_unit = _unit_points(facts, taxonomy, tag)
    chosen = unit if unit is not None else (_pick_unit(by_unit) if by_unit else "")
    concept = f"{taxonomy}:{tag}"
    reported: dict[tuple[str, str], SpanLeg] = {}
    for point in by_unit.get(chosen, ()):
        length_class = _length_class(point.start, point.end)
        if length_class not in _TTM_CLASSES:
            continue
        reported[(point.start, point.end)] = SpanLeg(
            start=point.start,
            end=point.end,
            length_class=length_class,
            value=float(point.value),
            accession=point.accession,
            concept_qname=concept,
            unit=point.unit,
        )
    quarters, breaks = _discrete_quarters(reported, weighted=weighted)
    return QuarterLegSet(
        reported=tuple(sorted(reported.values(), key=lambda leg: (leg.end, leg.start))),
        quarters=tuple(sorted(quarters.values(), key=lambda leg: (leg.end, leg.start))),
        breaks=tuple(breaks),
    )


def facts_ttm(
    facts: CompanyFacts,
    taxonomy: str,
    tag: str,
    *,
    unit: str | None = None,
    period_end: str | None = None,
    weighted: bool = False,
) -> TtmResult:
    """TTM over a company-facts document; comparison surface only."""
    metric = f"{taxonomy}:{tag}"
    leg_set = facts_quarter_legs(facts, taxonomy, tag, unit=unit, weighted=weighted)
    if not leg_set.reported and not leg_set.quarters:
        return TtmResult(
            metric=metric,
            value=None,
            status=QueryStatus.UNAVAILABLE,
            period_end=period_end,
            legs=(),
            route=None,
            reason=(
                "the company-facts document carries no duration points for this concept"
            ),
        )
    return _ttm_window(metric, leg_set, weighted=weighted, period_end=period_end)


def facts_eps_ttm(
    facts: CompanyFacts,
    *,
    income: tuple[str, str],
    shares: tuple[str, str],
    period_end: str | None = None,
    metric: str = "eps_basic",
) -> TtmResult:
    """Facts EPS as TTM net income over TTM weighted shares; never a sum."""
    income_result = facts_ttm(facts, *income, period_end=period_end)
    shares_result = facts_ttm(facts, *shares, period_end=period_end, weighted=True)
    if income_result.value is None or shares_result.value is None:
        failed = income_result if income_result.value is None else shares_result
        return TtmResult(
            metric=metric,
            value=None,
            status=QueryStatus.UNAVAILABLE,
            period_end=period_end,
            legs=(),
            route=None,
            reason=failed.reason,
        )
    value = round(income_result.value / shares_result.value, 4)
    return TtmResult(
        metric=metric,
        value=value,
        status=QueryStatus.DERIVED,
        period_end=income_result.period_end,
        legs=(income_result, shares_result),
        route="eps_ratio",
        reason=None,
    )


def facts_ttm_from_store(
    store_file: Path | str,
    cik: int,
    taxonomy: str,
    tag: str,
    *,
    unit: str | None = None,
    period_end: str | None = None,
    weighted: bool = False,
) -> TtmResult:
    """Facts TTM over the bulk facts store, for the comparison surface."""
    from edgar_sec.apps.client.companyfacts import CompanyFact
    from edgar_sec.pipelines.metadata_sync.facts_store import (
        read_facts_for_cik,
    )

    def convert(row: StoredFact) -> CompanyFact:
        return CompanyFact(
            taxonomy=row.taxonomy,
            tag=row.tag,
            unit=row.unit,
            value=row.value,
            start=row.start,
            end=row.end,
            accession=row.accession,
            form=row.form,
            filed=row.filed,
            fiscal_year=row.fiscal_year,
            fiscal_period=row.fiscal_period,
            frame=row.frame,
        )

    rows = read_facts_for_cik(store_file, cik)
    facts = CompanyFacts(
        cik=cik, entity_name="", facts=tuple(convert(row) for row in rows)
    )
    return facts_ttm(
        facts,
        taxonomy,
        tag,
        unit=unit,
        period_end=period_end,
        weighted=weighted,
    )


@dataclass(frozen=True)
class TtmComparisonRow:
    """One TTM value compared between the XBRL and facts surfaces."""

    cik: int
    metric: str
    period_end: str | None
    outcome: str
    xbrl_value: float | None
    facts_value: float | None


def compare_ttm(
    *,
    cik: int,
    metric: str,
    xbrl: TtmResult,
    facts: TtmResult,
) -> TtmComparisonRow | None:
    """Compare one TTM value; None when both surfaces are absent.

    AGREE needs the same closing end and a difference within the TTM
    window's own agreement tolerance; a different closing end diverges.
    """
    if xbrl.value is None and facts.value is None:
        return None
    if xbrl.value is None:
        outcome = FACTS_ONLY
    elif facts.value is None:
        outcome = PARSED_ONLY
    elif xbrl.period_end != facts.period_end:
        outcome = DIVERGE
    elif abs(xbrl.value - facts.value) <= max(
        0.01, 1e-6 * max(abs(xbrl.value), abs(facts.value))
    ):
        outcome = AGREE
    else:
        outcome = DIVERGE
    return TtmComparisonRow(
        cik=cik,
        metric=metric,
        period_end=xbrl.period_end or facts.period_end,
        outcome=outcome,
        xbrl_value=xbrl.value,
        facts_value=facts.value,
    )
