"""Tests for the company-facts client and its cross-check comparison."""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.companyfacts import (
    AGREE,
    DIVERGE,
    FACTS_ONLY,
    PARSED_ONLY,
    FactKey,
    compare_company_facts_to_parsed,
    fetch_company_facts,
    parsed_values_by_key,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import companyfacts_url
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.infra.sec_http.errors import PermanentHttpError
from tests.support import load_fixture


class _FakeHttp:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.calls.append(url)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_fetch_company_facts_maps_every_field_with_provenance() -> None:
    client = _FakeHttp(load_fixture("companyfacts_multi.json"))
    result = fetch_company_facts(320193, client=client)

    assert client.calls == [companyfacts_url("0000320193")]
    assert result.cik == 320193
    assert result.entity_name == "Apple Inc."
    assert len(result.facts) == 5

    shares = result.for_concept("dei", "EntityCommonStockSharesOutstanding")
    assert len(shares) == 1
    assert shares[0].unit == "shares"
    assert shares[0].value == 15115823000
    assert shares[0].start == ""
    assert shares[0].frame == "CY2024Q4I"

    assets = result.for_concept("us-gaap", "Assets", unit="USD")
    assert [point.end for point in assets] == ["2024-09-28", "2023-09-30"]
    first = assets[0]
    assert first.value == 364980000000
    assert first.accession == "0000320193-24-000123"
    assert first.form == "10-K"
    assert first.filed == "2024-11-01"
    assert first.fiscal_year == 2024
    assert first.fiscal_period == "FY"

    income = result.for_concept("us-gaap", "NetIncomeLoss")
    assert income[0].start == "2023-10-01"
    assert income[0].end == "2024-09-28"


def test_fetch_company_facts_sparse_document() -> None:
    result = fetch_company_facts(
        1750, client=_FakeHttp(load_fixture("companyfacts_sparse.json"))
    )

    assert result.entity_name == "AAR CORP"
    assert len(result.facts) == 1
    assert result.facts[0].value == 1135800000


def test_fetch_company_facts_absent_cik_is_empty() -> None:
    url = companyfacts_url("0000001750")
    client = _FakeHttp(PermanentHttpError(url, "not found", status_code=404))
    result = fetch_company_facts(1750, client=client)

    assert result.cik == 1750
    assert result.facts == ()
    assert fetch_company_facts(1750, client=_FakeHttp([1, 2])).facts == ()
    assert fetch_company_facts(1750, client=_FakeHttp({})).facts == ()


def test_compare_reports_the_four_outcome_classes() -> None:
    facts = fetch_company_facts(
        320193, client=_FakeHttp(load_fixture("companyfacts_multi.json"))
    )
    assets_key = FactKey("us-gaap", "Assets", "USD", "", "2024-09-28")
    income_key = FactKey("us-gaap", "NetIncomeLoss", "USD", "2023-10-01", "2024-09-28")
    equity_key = FactKey("us-gaap", "StockholdersEquity", "USD", "", "2024-09-28")
    parsed = {
        assets_key: 364980000000.0,
        income_key: 1.0,
        equity_key: 74101000000.0,
    }

    comparison = compare_company_facts_to_parsed(facts, parsed)

    by_key = {row.key: row for row in comparison.rows}
    assert by_key[assets_key].outcome == AGREE
    assert by_key[income_key].outcome == DIVERGE
    assert by_key[equity_key].outcome == PARSED_ONLY
    shares_key = FactKey(
        "dei", "EntityCommonStockSharesOutstanding", "shares", "", "2024-11-01"
    )
    assert by_key[shares_key].outcome == FACTS_ONLY
    assert comparison.counts == {AGREE: 1, DIVERGE: 1, FACTS_ONLY: 2, PARSED_ONLY: 1}
    assert comparison.agreement_rate == 0.5


def test_compare_uses_the_latest_filed_point_for_a_re_reported_key() -> None:
    facts = fetch_company_facts(
        320193, client=_FakeHttp(load_fixture("companyfacts_multi.json"))
    )
    income_key = FactKey("us-gaap", "NetIncomeLoss", "USD", "2023-10-01", "2024-09-28")

    comparison = compare_company_facts_to_parsed(
        facts,
        {income_key: 93736000000.0},
        concepts={("us-gaap", "NetIncomeLoss", "USD")},
    )

    (row,) = comparison.rows
    assert row.outcome == AGREE
    assert row.accession == "0000320193-25-000001"


def test_compare_concepts_restricts_both_sides() -> None:
    facts = fetch_company_facts(
        320193, client=_FakeHttp(load_fixture("companyfacts_multi.json"))
    )

    comparison = compare_company_facts_to_parsed(
        facts, {}, concepts={("us-gaap", "Assets", "USD")}
    )

    assert {row.key.tag for row in comparison.rows} == {"Assets"}
    assert comparison.agreement_rate is None


def test_parsed_values_by_key_shapes_the_join_keys() -> None:
    accession = AccessionNumber.from_any("0000320193-24-000123")
    instant = {
        "accession": accession,
        "concept_qname": "us-gaap:Assets",
        "unit": "USD",
        "period_type": "instant",
        "instant_date": "2024-09-28",
    }
    facts = (
        XbrlFact(value=10.0, **instant),
        XbrlFact(value=99.0, **instant),
        XbrlFact(value=1.0, dimensions={"axis": "member"}, **instant),
        XbrlFact(value="n/a", **instant),
        XbrlFact(
            accession=accession,
            concept_qname="us-gaap:NetIncomeLoss",
            value=3.5,
            unit="USD",
            period_type="duration",
            start_date="2023-10-01",
            end_date="2024-09-28",
        ),
    )

    parsed = parsed_values_by_key(facts)

    assert parsed == {
        FactKey("us-gaap", "Assets", "USD", "", "2024-09-28"): 10.0,
        FactKey("us-gaap", "NetIncomeLoss", "USD", "2023-10-01", "2024-09-28"): 3.5,
    }


def test_facade_company_facts_uses_the_facade_sec_client() -> None:
    from edgar_sec.apps.client.facade import Edgar

    http = _FakeHttp(load_fixture("companyfacts_sparse.json"))
    facade = Edgar(sec_client=http)

    result = facade.company_facts(1750)

    assert http.calls == [companyfacts_url("0000001750")]
    assert len(result.facts) == 1
