"""Tests for earnings extraction against the Step 6 fixture corpus."""

import gzip
from typing import Any

import pytest

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.earnings.extraction import (
    ExhibitPayload,
    extract_earnings_exhibit,
    extract_earnings_payloads,
)
from edgar_sec.engine.forms.earnings.models import EarningsExhibitResult
from edgar_sec.engine.forms.earnings.selection import select_exhibit_candidates
from tests.support import fixture_path, load_fixture

_MANIFEST: dict[str, Any] = load_fixture("earnings/manifest.json")
_FILINGS: list[dict[str, Any]] = _MANIFEST["filings"]
_BY_ACCESSION = {entry["accession"]: entry for entry in _FILINGS}


def _payload(accession: str, filename: str) -> bytes:
    return gzip.decompress(
        fixture_path(f"earnings/{accession}/{filename}.gz").read_bytes()
    )


def _filing(entry: dict[str, Any]) -> FilingAggregate:
    attachments = tuple(
        FilingAttachment(
            attachment_id=str(index),
            document_type="EX-99.1",
            filename=exhibit["name"],
            url="",
            fetcher=lambda a, acc=entry["accession"]: _payload(acc, a.filename),
        )
        for index, exhibit in enumerate(entry["exhibits"])
    )
    return FilingAggregate(
        accession=AccessionNumber.from_any(entry["accession"]),
        primary_cik=Cik(entry["cik"]),
        ciks=(Cik(entry["cik"]),),
        form=entry["form"],
        filing_date="2020-01-01",
        attachments=attachments,
    )


def _extract(accession: str) -> EarningsExhibitResult:
    return extract_earnings_exhibit(_filing(_BY_ACCESSION[accession]))


def _headline_pair(figure: Any) -> tuple[str, str] | None:
    if figure is None:
        return None
    return (figure.label, figure.value)


@pytest.mark.parametrize("accession", [entry["accession"] for entry in _FILINGS])
def test_fixture_effective_exhibit_and_table_inventory(accession: str) -> None:
    """Each specimen selects its recorded exhibit and table inventory."""
    entry = _BY_ACCESSION[accession]
    result = _extract(accession)
    assert result.exhibit is not None
    assert result.exhibit.filename == entry["effective_exhibit"]
    expected = next(
        e for e in entry["exhibits"] if e["name"] == entry["effective_exhibit"]
    )
    assert len(result.tables) == len(expected["tables"])
    for table, recorded in zip(result.tables, expected["tables"], strict=True):
        assert table.table_index == recorded["idx"]
        assert list(table.roles) == recorded["roles"]


@pytest.mark.parametrize("accession", [entry["accession"] for entry in _FILINGS])
def test_fixture_headline_figures(accession: str) -> None:
    """Headline figures match the record exactly, or are honestly absent."""
    entry = _BY_ACCESSION[accession]
    result = _extract(accession)
    recorded = entry["headline"]
    if recorded is None:
        assert result.headline is None
        return
    assert result.headline is not None
    assert result.headline.locus == entry["headline_locus"]
    for key in ("revenue", "net_income", "eps"):
        expected = recorded[key]
        got = _headline_pair(getattr(result.headline, key))
        want = None if expected is None else (expected["label"], expected["value"])
        assert got == want


def test_statement_table_specimen_has_no_review_signals() -> None:
    """A clean statement specimen extracts with no accounting remainder."""
    result = _extract("0001437749-14-013440")
    assert result.review_signals == ()
    assert result.image_exhibits == ("ex99-1img001.jpg",)


def test_summary_table_specimen_reads_summary_first() -> None:
    """The agent-mangled summary specimen serves its headline from table zero."""
    result = _extract("0000950123-07-001176")
    assert result.headline is not None
    assert result.headline.source_table_index == 0


def test_multi_exhibit_fallback_is_signalled() -> None:
    """Falling past EX-99.2 to the statement exhibit is accounted."""
    result = _extract("0001402829-08-000026")
    assert [s.kind for s in result.review_signals] == ["exhibit_fallback"]


def test_plain_text_exhibit_is_a_review_signal() -> None:
    """A plain-text exhibit serves text and no deterministic figures."""
    result = _extract("0000943374-04-000332")
    assert result.tables == ()
    assert result.headline is None
    assert result.text != ""
    assert [s.kind for s in result.review_signals] == ["text_exhibit"]


def test_sixk_tables_extract_but_headline_is_review_signal() -> None:
    """6-K tables are deterministic; headline figures are not served."""
    result = _extract("0001193125-05-202866")
    assert len(result.tables) == 2
    assert result.headline is None
    assert [s.kind for s in result.review_signals] == ["sixk_headline_vocabulary"]


def test_pdf_exhibit_joins_the_text_class() -> None:
    """A PDF exhibit converts through the PDF route, then signals as text."""
    result = _extract("0001279569-24-000173")
    assert result.tables == ()
    assert result.headline is None
    assert result.text != ""
    assert [s.kind for s in result.review_signals] == ["text_exhibit"]
    assert result.review_signals[0].specimen_class.startswith("PDF exhibits")


def test_no_tables_html_exhibit_is_a_review_signal() -> None:
    """An HTML exhibit with no statement tables accounts its prose headline."""
    result = _extract("0001104659-18-039497")
    assert result.tables == ()
    assert [s.kind for s in result.review_signals] == ["no_statement_tables"]


def test_no_ex99_exhibit_is_honest_absence() -> None:
    """A filing with no EX-99 filename carries the absence reason."""
    candidates = select_exhibit_candidates((("primary.htm", "8-K"),))
    result = extract_earnings_payloads(
        accession="0000000000-00-000001", form="8-K", payloads=()
    )
    assert candidates == ()
    assert result.exhibit is None
    assert result.absence_reason == "no_ex99_exhibit"


def test_image_only_exhibit_is_refused_not_ocred() -> None:
    """An image-only candidate set is inventoried and refused."""
    candidates = select_exhibit_candidates((("ex99-1img001.jpg", "GRAPHIC"),))
    payloads = tuple(ExhibitPayload(candidate=c, raw=None) for c in candidates)
    result = extract_earnings_payloads(
        accession="0000000000-00-000001", form="8-K", payloads=payloads
    )
    assert result.tables == ()
    assert result.image_exhibits == ("ex99-1img001.jpg",)
    assert [s.kind for s in result.review_signals] == ["image_exhibit_refused"]


def test_unacquired_payload_is_a_review_signal() -> None:
    """A selected exhibit whose payload is missing is accounted, not dropped."""
    candidates = select_exhibit_candidates((("ex99-1.htm", "EX-99.1"),))
    payloads = tuple(ExhibitPayload(candidate=c, raw=None) for c in candidates)
    result = extract_earnings_payloads(
        accession="0000000000-00-000001", form="8-K", payloads=payloads
    )
    assert [s.kind for s in result.review_signals] == ["payload_not_acquired"]


def test_curly_apostrophe_balance_sheet_specimen_earns_its_role() -> None:
    """A balance sheet whose equity label carries U+2019 still earns the role."""
    html = (
        "<html><body><table>"
        "<tr><td>Total assets</td><td>100</td></tr>"
        "<tr><td>Total liabilities</td><td>40</td></tr>"
        "<tr><td>Total stockholders\u2019 equity</td><td>60</td></tr>"
        "</table></body></html>"
    ).encode()
    candidates = select_exhibit_candidates((("ex99-1.htm", "EX-99.1"),))
    payloads = tuple(ExhibitPayload(candidate=c, raw=html) for c in candidates)
    result = extract_earnings_payloads(
        accession="0000000000-00-000001", form="8-K", payloads=payloads
    )
    assert any("balance_sheet" in table.roles for table in result.tables)
