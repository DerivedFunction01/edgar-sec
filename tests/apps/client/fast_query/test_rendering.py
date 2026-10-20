from __future__ import annotations

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query import rendering
from edgar_sec.apps.client.fast_query.rendering import make_filing_renderer
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik


def _filing(form: str, filename: str, content: bytes) -> FilingAggregate:
    cik = Cik.from_raw(320193)
    return FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=cik,
        ciks=(cik,),
        form=form,
        filing_date="2023-11-03",
        primary_document_path=filename,
        fetcher=lambda _filing: content,
    )


def test_raw_facade_operation_does_not_attempt_lazy_index(
    tmp_path, monkeypatch
) -> None:
    content = b"<html><h1>Exhibit 99.1</h1></html>"
    filing = _filing("4", "ex99.htm", content)
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    calls: list[str] = []
    monkeypatch.setattr(
        rendering,
        "recover_inverted_primary",
        lambda *_args: calls.append("recovery") or None,
    )

    result = make_filing_renderer(cache, operation="raw")(filing)

    assert result == content
    assert calls == []


def test_form_4_xml_mismatch_returns_raw_when_recovery_fails(
    tmp_path, monkeypatch
) -> None:
    content = (
        b"<html><body><h1>Exhibit 99.1</h1><p>Acme announced a deal.</p></body></html>"
    )
    filing = _filing("4", "ex99.htm", content)
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    calls: list[str] = []
    monkeypatch.setattr(
        rendering,
        "recover_inverted_primary",
        lambda *_args: calls.append("recovery") or None,
    )

    result = make_filing_renderer(cache, operation="render_to_xml")(filing)

    assert result == content
    assert calls == ["recovery"]


def test_unsupported_form_4_text_operation_returns_raw(tmp_path) -> None:
    content = b"<html><body>Ownership filing</body></html>"
    filing = _filing("4", "ownership.htm", content)
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")

    result = make_filing_renderer(cache, operation="render_to_txt")(filing)

    assert result == content


def test_unsupported_form_4_text_operation_skips_recovery(
    tmp_path, monkeypatch
) -> None:
    content = b"<html><body><h1>Exhibit 99.1</h1></body></html>"
    filing = _filing("4", "ex99.htm", content)
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    calls: list[str] = []
    monkeypatch.setattr(
        rendering,
        "recover_inverted_primary",
        lambda *_args: calls.append("recovery") or None,
    )

    result = make_filing_renderer(cache, operation="render_to_txt")(filing)

    assert result == content
    assert calls == []


def test_generic_text_render_remains_best_effort_after_recovery_miss(
    tmp_path, monkeypatch
) -> None:
    content = (
        b"<html><body><h1>Exhibit 99.1</h1><p>Acme announced a deal.</p></body></html>"
    )
    filing = _filing("10-K", "ex99.htm", content)
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    monkeypatch.setattr(rendering, "recover_inverted_primary", lambda *_args: None)

    result = make_filing_renderer(cache, operation="render_to_txt")(filing)

    assert isinstance(result, str)
    assert "Acme announced a deal" in result


def test_form_4_xml_renders_recovered_primary(tmp_path, monkeypatch) -> None:
    original = b"<html><h1>Exhibit 99.1</h1><p>Acme press release.</p></html>"
    recovered = (
        b"<html><body><h1>FORM 4</h1><p>Issuer Acme</p>"
        b"<p>Reporting Owner</p><p>Relationship of Reporting Person</p>"
        b"<p>Table I - Non-Derivative</p></body></html>"
    )
    filing = _filing("4", "ex99.htm", original)
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    calls: list[str] = []

    def recover(*_args):
        calls.append("recovery")
        object.__setattr__(filing, "primary_document_path", "form4.htm")
        return recovered

    monkeypatch.setattr(rendering, "recover_inverted_primary", recover)

    result = make_filing_renderer(cache, operation="render_to_xml")(filing)

    assert isinstance(result, str)
    assert "<documentType>4</documentType>" in result
    assert calls == ["recovery"]
