"""Tests for the company operation's facts cross-check section."""

from __future__ import annotations

from types import SimpleNamespace

from edgar_sec.apps.client import operator
from edgar_sec.apps.client.companyfacts import CompanyFact, CompanyFacts
from edgar_sec.apps.client.operator_company_facts import facts_check_section
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact


def _fact(tag: str, value: float, end: str) -> CompanyFact:
    return CompanyFact(
        taxonomy="us-gaap",
        tag=tag,
        unit="USD",
        value=value,
        start="",
        end=end,
        accession="0000000001-24-000001",
        form="10-K",
        filed="2025-02-01",
        fiscal_year=2024,
        fiscal_period="FY",
    )


def _parsed(qname: str, value: float, end: str) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any("0000000001-24-000001"),
        concept_qname=qname,
        value=value,
        unit="USD",
        period_type="instant",
        instant_date=end,
    )


class _FakeFacade:
    """Facade stand-in serving one canned facts document."""

    def __init__(self, facts: CompanyFacts) -> None:
        self._facts = facts
        self.calls: list[str] = []

    def company_facts(self, cik):
        self.calls.append(str(cik))
        return self._facts


def _company(facts) -> SimpleNamespace:
    return SimpleNamespace(xbrl=lambda: SimpleNamespace(facts=facts))


def test_section_renders_counts_and_rows_per_outcome() -> None:
    document = CompanyFacts(
        cik=1,
        entity_name="Acme",
        facts=(
            _fact("Assets", 10.0, "2024-09-28"),
            _fact("Revenues", 7.0, "2024-09-28"),
        ),
    )
    facade = _FakeFacade(document)
    session = operator.ClientSession(facade=facade)
    company = _company(
        (
            _parsed("us-gaap:Assets", 10.0, "2024-09-28"),
            _parsed("us-gaap:Liabilities", 3.0, "2024-09-28"),
        )
    )

    section = facts_check_section(company, session, "0000000001")

    assert facade.calls == ["0000000001"]
    assert section["cik"] == "0000000001"
    assert section["counts"] == {
        "agree": 1,
        "diverge": 0,
        "facts_only": 1,
        "parsed_only": 1,
    }
    assert section["agreement_rate"] == 1.0
    assert (section["total"], section["shown"]) == (3, 3)
    by_tag = {row["tag"]: row for row in section["rows"]}
    assert by_tag["Assets"]["outcome"] == "agree"
    assert by_tag["Revenues"]["outcome"] == "facts_only"
    assert by_tag["Liabilities"]["outcome"] == "parsed_only"
    assert by_tag["Liabilities"]["facts_value"] is None


def test_section_without_parsed_surface_is_all_facts_only() -> None:
    document = CompanyFacts(
        cik=1, entity_name="Acme", facts=(_fact("Assets", 10.0, "2024-09-28"),)
    )
    session = operator.ClientSession(facade=_FakeFacade(document))
    company = SimpleNamespace(xbrl=lambda: None)

    section = facts_check_section(company, session, "0000000001")

    assert section["counts"] == {
        "agree": 0,
        "diverge": 0,
        "facts_only": 1,
        "parsed_only": 0,
    }
    assert section["agreement_rate"] is None


def test_section_caps_rendered_rows_and_declares_the_clamp() -> None:
    document = CompanyFacts(
        cik=1,
        entity_name="Acme",
        facts=tuple(_fact("Assets", float(n), f"20{n:02d}-01-01") for n in range(60)),
    )
    session = operator.ClientSession(facade=_FakeFacade(document))

    section = facts_check_section(_company(()), session, "0000000001")

    assert section["total"] == 60
    assert section["shown"] == 50
    assert len(section["rows"]) == 50
    assert section["counts"]["facts_only"] == 60
