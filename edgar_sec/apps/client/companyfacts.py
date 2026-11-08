"""Company-facts lookups: SEC-reported values for one whole company.

This is a cross-check surface only: values are served exactly as the SEC
reports them, with per-point provenance, and never feed the statements
machinery. The join to parsed facts exists only as the comparison below.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass

from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import companyfacts_url
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.errors import PermanentHttpError, RetryExhausted

__all__ = [
    "AGREE",
    "DIVERGE",
    "FACTS_ONLY",
    "PARSED_ONLY",
    "CompanyFact",
    "CompanyFacts",
    "FactKey",
    "FactsComparison",
    "FactsComparisonRow",
    "compare_company_facts_to_parsed",
    "fetch_company_facts",
    "iter_company_facts",
]


@dataclass(frozen=True, slots=True)
class FactKey:
    """The join identity of one reported fact: concept, unit, and period."""

    taxonomy: str
    tag: str
    unit: str
    start: str  # "" for an instant point
    end: str


@dataclass(frozen=True, slots=True)
class CompanyFact:
    """One SEC-reported data point for a company, with its provenance."""

    taxonomy: str
    tag: str
    unit: str
    value: int | float
    start: str
    end: str
    accession: str
    form: str
    filed: str
    fiscal_year: int | None
    fiscal_period: str
    frame: str = ""

    @property
    def key(self) -> FactKey:
        """The join identity of this point."""
        return FactKey(self.taxonomy, self.tag, self.unit, self.start, self.end)


@dataclass(frozen=True, slots=True)
class CompanyFacts:
    """One company's full SEC facts document, mapped to typed rows."""

    cik: int
    entity_name: str
    facts: tuple[CompanyFact, ...]

    def for_concept(
        self, taxonomy: str, tag: str, *, unit: str | None = None
    ) -> tuple[CompanyFact, ...]:
        """This document's points for one concept, optionally one unit."""
        return tuple(
            fact
            for fact in self.facts
            if fact.taxonomy == taxonomy
            and fact.tag == tag
            and (unit is None or fact.unit == unit)
        )


def iter_company_facts(payload: object) -> Iterator[CompanyFact]:
    """Yield typed rows from a parsed companyfacts document, per concept."""
    if not isinstance(payload, dict):
        return
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return
    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue
        for tag, concept in concepts.items():
            if not isinstance(concept, dict):
                continue
            units = concept.get("units")
            if not isinstance(units, dict):
                continue
            for unit, points in units.items():
                if not isinstance(points, list):
                    continue
                for point in points:
                    if not isinstance(point, dict):
                        continue
                    value = point.get("val")
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        continue
                    fiscal_year = point.get("fy")
                    yield CompanyFact(
                        taxonomy=str(taxonomy),
                        tag=str(tag),
                        unit=str(unit),
                        value=value,
                        start=str(point.get("start", "")),
                        end=str(point.get("end", "")),
                        accession=str(point.get("accn", "")),
                        form=str(point.get("form", "")),
                        filed=str(point.get("filed", "")),
                        fiscal_year=(
                            fiscal_year if isinstance(fiscal_year, int) else None
                        ),
                        fiscal_period=str(point.get("fp", "")),
                        frame=str(point.get("frame", "")),
                    )


def fetch_company_facts(
    cik: str | int | Cik,
    *,
    client: SecHttpClient,
) -> CompanyFacts:
    """Fetch one company's facts document; empty when the CIK is absent."""
    cik_inst = cik if isinstance(cik, Cik) else Cik.from_raw(cik)
    url = companyfacts_url(cik_inst.to_10digit())
    try:
        payload = client.get_json(url)
    except (PermanentHttpError, RetryExhausted):
        return CompanyFacts(cik=int(cik_inst), entity_name="", facts=())
    if not isinstance(payload, dict):
        return CompanyFacts(cik=int(cik_inst), entity_name="", facts=())
    return CompanyFacts(
        cik=int(cik_inst),
        entity_name=str(payload.get("entityName", "")),
        facts=tuple(iter_company_facts(payload)),
    )


AGREE = "agree"
DIVERGE = "diverge"
FACTS_ONLY = "facts_only"
PARSED_ONLY = "parsed_only"


@dataclass(frozen=True, slots=True)
class FactsComparisonRow:
    """One concept-period key's cross-check outcome, facts vs parsed."""

    key: FactKey
    outcome: str
    facts_value: int | float | None
    parsed_value: float | None
    accession: str  # the facts point that carried the key; "" when none did


@dataclass(frozen=True, slots=True)
class FactsComparison:
    """One company's SEC facts cross-checked against its parsed facts."""

    cik: int
    rows: tuple[FactsComparisonRow, ...]

    @property
    def counts(self) -> dict[str, int]:
        """Outcome counts over the compared key set."""
        counts = {AGREE: 0, DIVERGE: 0, FACTS_ONLY: 0, PARSED_ONLY: 0}
        for row in self.rows:
            counts[row.outcome] += 1
        return counts

    @property
    def agreement_rate(self) -> float | None:
        """Agreements over keys present on both sides; None when disjoint."""
        counts = self.counts
        both = counts[AGREE] + counts[DIVERGE]
        if both == 0:
            return None
        return counts[AGREE] / both


def _current_points(facts: CompanyFacts) -> dict[FactKey, CompanyFact]:
    """Each key's current facts point: the latest filed report wins.

    A re-reported key carries every vintage in the document; the
    cross-check compares against the currently presented report.
    """
    current: dict[FactKey, CompanyFact] = {}
    for fact in facts.facts:
        held = current.get(fact.key)
        if held is None or (fact.filed, fact.accession) > (held.filed, held.accession):
            current[fact.key] = fact
    return current


def compare_company_facts_to_parsed(
    facts: CompanyFacts,
    parsed_by_key: Mapping[FactKey, float | None],
    *,
    concepts: Collection[tuple[str, str, str]] | None = None,
) -> FactsComparison:
    """Compare one company's SEC facts with its parsed values, key by key.

    A parsed None (or missing key) is an absence, not a zero: the row
    is facts-only, never a divergence.
    """
    wanted = set(concepts) if concepts is not None else None

    def in_scope(key: FactKey) -> bool:
        return wanted is None or (key.taxonomy, key.tag, key.unit) in wanted

    rows: list[FactsComparisonRow] = []
    current = _current_points(facts)
    facts_keys: set[FactKey] = set()
    for key in sorted(current, key=lambda item: (item.taxonomy, item.tag, item.end)):
        if not in_scope(key):
            continue
        facts_keys.add(key)
        point = current[key]
        parsed = parsed_by_key.get(key)
        if parsed is None:
            outcome = FACTS_ONLY
        elif float(point.value) == float(parsed):
            outcome = AGREE
        else:
            outcome = DIVERGE
        rows.append(
            FactsComparisonRow(
                key=key,
                outcome=outcome,
                facts_value=point.value,
                parsed_value=parsed,
                accession=point.accession,
            )
        )
    for key in sorted(set(parsed_by_key) - facts_keys, key=lambda item: item.end):
        if not in_scope(key):
            continue
        parsed = parsed_by_key[key]
        if parsed is None:
            continue
        rows.append(
            FactsComparisonRow(
                key=key,
                outcome=PARSED_ONLY,
                facts_value=None,
                parsed_value=parsed,
                accession="",
            )
        )
    return FactsComparison(cik=facts.cik, rows=tuple(rows))
