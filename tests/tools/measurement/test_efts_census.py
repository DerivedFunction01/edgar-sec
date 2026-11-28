"""Paced EFTS census driver: legs and specimen classes over fakes."""

from __future__ import annotations

import pytest

from edgar_sec.domain.sec_urls import archives_url, index_json_url_for
from edgar_sec.tools.measurement.efts_census import (
    CensusConfig,
    ProbeExhausted,
    classify_segment,
    count_tables,
    draw_sample,
    efts_url,
    extract_segment,
    list_docs,
    probe,
    run_census,
    specimen_leg,
    totals_leg,
)
from tests.support.http import FakeSession, build_test_http

FORMS = ("10-K", "10-K/A")
PROSE = (
    "The company is party to various claims and proceedings arising "
    "in the ordinary course of business, and management believes the "
    "outcome of these matters will not be material to the financial "
    "statements of the company as a whole. "
)


class RecordingSleep:
    """Sleeper double: records every requested wait, never waits."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_config(**overrides) -> CensusConfig:
    """The two-year test step config, with per-test overrides."""
    config = {
        "phrase": "Item 3. Legal Proceedings",
        "broad_phrase": "legal proceedings",
        "forms": list(FORMS),
        "start_year": 2001,
        "end_year": 2002,
        "end_date": "2002-12-31",
        "prefix": "test",
        "pool_size": 100,
        "cooldown_s": 600.0,
        "pace_s": 1.1,
        "totals_pace_s": 0.25,
        "probe_backoffs_s": [30.0, 60.0],
    }
    config.update(overrides)
    return CensusConfig.from_config(config)


def efts_payload(total: int, hits: list[dict]) -> dict:
    """One EFTS search-index response body."""
    return {"hits": {"total": {"value": total, "relation": "eq"}, "hits": hits}}


def hit(accession: str, cik: str, form: str, date: str) -> dict:
    """One EFTS hit in the endpoint's recorded shape."""
    return {
        "_source": {
            "adsh": accession,
            "ciks": [cik],
            "form": form,
            "file_date": date,
        }
    }


def register_efts(
    session: FakeSession,
    cfg: CensusConfig,
    year: int,
    form: str,
    total: int,
    hits: list[dict],
) -> None:
    """Register one year/form shard response at its driver URL."""
    url = efts_url(cfg.phrase, form, f"{year}-01-01", f"{year}-12-31", 0, cfg.pool_size)
    session.register(url, efts_payload(total, hits))


def register_doc(session: FakeSession, cik: str, accession: str, body: str) -> None:
    """Register a filing index and its main document body."""
    index_url = index_json_url_for(accession, cik)
    session.register(
        index_url,
        {
            "directory": {
                "item": [
                    {"name": "ex-99.htm", "size": "900000"},
                    {"name": "a10-k.htm", "size": "500000"},
                ]
            }
        },
    )
    session.register_bytes(
        archives_url(cik, accession, "a10-k.htm"), body.encode("utf-8")
    )
    session.register_bytes(
        archives_url(cik, accession, "ex-99.htm"), b"<html>exhibit</html>"
    )


def doc(segment_inner: str) -> str:
    """A filing document whose Item 3 segment wraps the given prose."""
    return (
        "<html><body><p>Item 3. Legal Proceedings. "
        + segment_inner
        + "</p><p>Item 4. Mine Safety Disclosures.</p></body></html>"
    )


def test_efts_url_shape():
    url = efts_url(
        "Item 3. Legal Proceedings", "10-K", "2001-01-01", "2001-12-31", 0, 100
    )
    assert url.startswith("https://efts.sec.gov/LATEST/search-index?")
    assert "q=%22Item+3.+Legal+Proceedings%22" in url
    assert "forms=10-K" in url and "size=100" in url


def test_classify_segment_classes():
    assert classify_segment("Item 3. Legal Proceedings. None.") == "none-or-na-stub"
    assert classify_segment("x" * 300) == "substantive-prose"
    opener = "None. " + "x" * 300
    assert classify_segment(opener) == "none-or-na-stub"
    incorporated = "The disclosure is incorporated by reference here. " + "x" * 300
    assert classify_segment(incorporated) == "incorporated-by-reference"
    xref = "Matters are described in the notes to the statements. " + "x" * 300
    assert classify_segment(xref) == "cross-reference-short"
    long_xref = "Matters are described in the notes to the statements. " + "x" * 1500
    assert classify_segment(long_xref) == "substantive-prose"


def test_extract_segment_longest_and_cap():
    text = (
        "Item 3. Legal Proceedings. Short. Item 4. Next. "
        "Item 3. Legal Proceedings. " + PROSE * 3 + " Item 4. Next."
    )
    found = extract_segment(text)
    assert found is not None
    segment, capped, headings = found
    assert headings == 2
    assert segment.startswith("Item 3. Legal Proceedings. The company")
    assert capped is False
    big = "Item 3. Legal Proceedings. " + "x" * 130_000
    segment, capped, _ = extract_segment(big)
    assert len(segment) == 120_000 and capped is True
    assert extract_segment("no heading here") is None


def test_count_tables_span():
    raw = (
        "<p>Legal Proceedings</p><table></table>"
        "<p>Item 3. Legal Proceedings.</p><table></table><table></table>"
        "<p>Item 4. Other.</p><table></table>"
    )
    assert count_tables(raw) == 2
    assert count_tables("<p>nothing</p>") == -1


def test_draw_sample_positions():
    pool = {
        2001: [{"accession": a} for a in ("a1", "a2", "a3", "a4", "a5")],
        2002: [{"accession": "b1"}],
        2003: [],
    }
    sample = draw_sample(pool)
    assert [r["accession"] for r in sample] == ["a1", "a3", "a5", "b1"]
    assert [r["pool_year"] for r in sample] == [2001, 2001, 2001, 2002]


def test_list_docs_listing_fallback():
    session = FakeSession()
    client = build_test_http(session)
    cik, accession = "12345", "0000012345-01-000001"
    page = '<a href="b10-k.htm">x</a><a href="a10-k.htm">y</a>'
    session.register_bytes(archives_url(cik, accession, ""), page.encode())
    assert list_docs(client, cik, accession) == [
        ("a10-k.htm", 0),
        ("b10-k.htm", 0),
    ]
    assert list_docs(client, "99999", "0000099999-01-000001") == []


def test_probe_exhaustion_records_backoffs():
    session = FakeSession()
    client = build_test_http(session)
    cfg = make_config()
    sample = [{"accession": f"000000000{i}-01-000001", "cik": "1"} for i in range(6)]
    sleep = RecordingSleep()
    assert probe(client, cfg, sample, sleep) is False
    assert sleep.calls == [30.0, 60.0]
    with pytest.raises(ProbeExhausted):
        specimen_leg(client, cfg, sample, RecordingSleep())


def scenario_session(cfg: CensusConfig) -> FakeSession:
    """The two-year faked transport: totals, pools, and six specimens."""
    session = FakeSession()
    pools = {
        2001: [
            ("0000000001-01-000001", "101", "10-K", "stub"),
            ("0000000002-01-000002", "102", "10-K", None),
            ("0000000003-01-000003", "103", "10-K/A", "substantive"),
            ("0000000004-01-000004", "104", "10-K", None),
            ("0000000005-01-000005", "105", "10-K/A", "xref"),
        ],
        2002: [
            ("0000000006-02-000006", "106", "10-K", "not-found"),
            ("0000000007-02-000007", "107", "10-K", None),
            ("0000000008-02-000008", "108", "10-K/A", "error"),
            ("0000000009-02-000009", "109", "10-K", None),
            ("0000000010-02-000010", "110", "10-K/A", "incorporated"),
        ],
    }
    totals = {2001: (111, 22), 2002: (333, 44)}
    for year, rows in pools.items():
        for form in FORMS:
            form_hits = [
                hit(a, cik, f, f"{year}-03-01")
                for a, cik, f, _kind in rows
                if f == form
            ]
            total = totals[year][FORMS.index(form)]
            register_efts(session, cfg, year, form, total, form_hits)
    broad_url = efts_url(cfg.broad_phrase, "10-K", "2001-01-01", cfg.end_date, 0, 100)
    session.register(broad_url, efts_payload(10_000, []))
    bodies = {
        "stub": doc("None."),
        "substantive": doc(PROSE * 4),
        "xref": doc(
            "The matters are described in the notes to the financial "
            "statements. " + PROSE
        ),
        "not-found": "<html><body><p>Item 2. Properties.</p></body></html>",
        "incorporated": doc(
            "The proceedings disclosure is incorporated by reference "
            "from the proxy statement. " + PROSE
        ),
    }
    for rows in pools.values():
        for accession, cik, _form, kind in rows:
            if kind in bodies:
                register_doc(session, cik, accession, bodies[kind])
    return session


def test_run_census_end_to_end():
    cfg = make_config()
    client = build_test_http(scenario_session(cfg))
    sleep = RecordingSleep()
    result = run_census(client, cfg, sleep)
    summary = result["summary"]
    assert summary["year_totals_q1"] == {
        "2001": [111, 22],
        "2002": [333, 44],
    }
    assert summary["year_totals_q1_sums"] == {"10-K": 444, "10-K/A": 66}
    assert summary["broad_phrase_10k_total_capped"] == 10_000
    assert summary["pool_sizes_by_year"] == {"2001": 5, "2002": 5}
    assert [r["accession"] for r in result["sample"]] == [
        "0000000001-01-000001",
        "0000000003-01-000003",
        "0000000005-01-000005",
        "0000000006-02-000006",
        "0000000008-02-000008",
        "0000000010-02-000010",
    ]
    assert summary["class_counts"] == {
        "none-or-na-stub": 1,
        "substantive-prose": 1,
        "cross-reference-short": 1,
        "heading-not-found": 1,
        "fetch-error": 1,
        "incorporated-by-reference": 1,
    }
    assert summary["measured_n"] == 5
    assert summary["fetch_errors"] == 1
    assert summary["sample_n"] == 6
    assert sleep.calls.count(600.0) == 1
    assert sleep.calls.count(1.1) == 6
    assert sleep.calls.count(0.25) == 6


def test_totals_leg_error_is_none_not_fatal():
    cfg = make_config()
    session = FakeSession()
    register_efts(session, cfg, 2001, "10-K", 5, [])
    client = build_test_http(session)
    sleep = RecordingSleep()
    year_totals, broad = totals_leg(client, cfg, sleep)
    assert year_totals[2001] == [5, None]
    assert year_totals[2002] == [None, None]
    assert broad is None
