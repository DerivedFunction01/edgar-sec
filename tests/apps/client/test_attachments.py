"""Tests for the Attachments collection, its selectors, and attachment accessors."""

from pathlib import Path

from edgar_sec.apps.client.attachments import Attachments
from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.fast_query.loaders import make_attachment_loader
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.forms.earnings.selection import select_exhibit_candidates


def _attachments() -> tuple[FilingAttachment, ...]:
    return (
        FilingAttachment(
            attachment_id="a1",
            document_type="10-K",
            filename="aapl-20230930.htm",
            url="https://www.sec.gov/aapl-20230930.htm",
            sequence=1,
            role="primary",
        ),
        FilingAttachment(
            attachment_id="a2",
            document_type="EX-21.1",
            filename="aapl_ex21.htm",
            url="https://www.sec.gov/aapl_ex21.htm",
            sequence=5,
            role="exhibit",
        ),
        FilingAttachment(
            attachment_id="a3",
            document_type="EX-99.1",
            filename="ex99_1.htm",
            url="https://www.sec.gov/ex99_1.htm",
            sequence=6,
            role="exhibit",
        ),
        FilingAttachment(
            attachment_id="a4",
            document_type="GRAPHIC",
            filename="chart.jpg",
            url="https://www.sec.gov/chart.jpg",
            sequence=7,
            role="graphic",
        ),
        FilingAttachment(
            attachment_id="a5",
            document_type="XML",
            filename="data.xml",
            url="https://www.sec.gov/data.xml",
            sequence=3,
            table_kind="data_file",
            role="data_file",
        ),
        FilingAttachment(
            attachment_id="a6",
            document_type="EX-101.CAL",
            filename="aapl_cal.xml",
            url="https://www.sec.gov/aapl_cal.xml",
            sequence=8,
            role="exhibit",
        ),
        FilingAttachment(
            attachment_id="a7",
            document_type="EX-32.1",
            filename="ex32.htm",
            url="https://www.sec.gov/ex32.htm",
            role="exhibit",
        ),
        FilingAttachment(
            attachment_id="a8",
            document_type="EX-99.2",
            filename="q3results.htm",
            url="https://www.sec.gov/q3results.htm",
            sequence=9,
            role="exhibit",
        ),
    )


def _ids(selection: Attachments) -> list[str]:
    return [a.attachment_id for a in selection]


def test_enumeration_is_inventory_identical() -> None:
    source = _attachments()
    collection = Attachments(source)
    assert len(collection) == len(source)
    assert list(collection) == list(source)
    for picked, original in zip(collection, source):
        assert picked is original


def test_selectors_return_matching_subsets() -> None:
    collection = Attachments(_attachments())
    assert _ids(collection.by_role("exhibit")) == ["a2", "a3", "a6", "a7", "a8"]
    assert _ids(collection.by_role("primary")) == ["a1"]
    assert _ids(collection.primary()) == ["a1"]
    assert _ids(collection.by_role("data_file")) == ["a5"]
    assert _ids(collection.graphics()) == ["a4"]
    assert _ids(collection.by_type("ex-21.1")) == ["a2"]
    assert _ids(collection.by_type("GRAPHIC")) == ["a4"]
    assert _ids(collection.by_type("10-Q")) == []
    assert _ids(collection.by_filename("AAPL_EX21.HTM")) == ["a2"]
    assert _ids(collection.by_filename("missing.htm")) == []
    assert _ids(collection.by_sequence(5)) == ["a2"]
    assert _ids(collection.by_sequence(999)) == []
    chained = collection.exhibits().by_type("EX-99.1")
    assert _ids(chained) == ["a3"]
    for picked in collection.by_role("exhibit"):
        assert any(picked is original for original in collection.items)


def test_exhibits_and_exhibit_selection() -> None:
    collection = Attachments(_attachments())
    assert _ids(collection.exhibits()) == ["a2", "a3", "a6", "a7", "a8"]
    assert _ids(collection.exhibits("21")) == ["a2"]
    assert _ids(collection.exhibits(types=("99",))) == ["a3", "a8"]
    assert _ids(collection.exhibits("EX-101")) == ["a6"]
    assert _ids(collection.exhibits("10")) == []

    by_id = {a.attachment_id: a for a in collection.items}
    assert collection.exhibit("21") is by_id["a2"]
    assert collection.exhibit("EX-21.1") is by_id["a2"]
    assert collection.exhibit(99) is by_id["a3"]
    assert collection.exhibit("32") is by_id["a7"]
    assert collection.exhibit("q3results") is by_id["a8"]
    assert collection.exhibit("10") is None
    assert collection.exhibit("chart") is None


def test_exhibit_selection_agrees_with_earnings_surface() -> None:
    collection = Attachments(_attachments())
    pairs = tuple((a.filename, a.document_type) for a in collection.items)
    candidates = select_exhibit_candidates(pairs)
    earnings_picked = {c.filename for c in candidates if c.exhibit_number == 1}
    assert earnings_picked == {"ex99_1.htm"}
    picked = collection.exhibit(99)
    assert picked is not None
    assert picked.filename in earnings_picked
    typed = collection.exhibits("99")
    assert {a.filename for a in typed} >= earnings_picked


def test_state_from_storage_path_and_presence(tmp_path: Path) -> None:
    stored = tmp_path / "held.htm"
    stored.write_bytes(b"<html>held</html>")
    local = FilingAttachment(
        attachment_id="s1",
        document_type="10-K",
        filename="held.htm",
        url="",
        storage_path=stored,
    )
    assert local.state == "acquired"
    assert local.content() == b"<html>held</html>"

    held = FilingAttachment(
        attachment_id="s2",
        document_type="10-K",
        filename="x.htm",
        url="",
        presence=lambda _a: True,
    )
    assert held.state == "acquired"
    missing = FilingAttachment(
        attachment_id="s3",
        document_type="10-K",
        filename="x.htm",
        url="",
        presence=lambda _a: False,
    )
    assert missing.state == "not_acquired"
    bare = FilingAttachment(
        attachment_id="s4", document_type="10-K", filename="x.htm", url=""
    )
    assert bare.state == "not_acquired"


def test_content_and_rendered_text_accessors() -> None:
    att = FilingAttachment(
        attachment_id="c1",
        document_type="EX-99.1",
        filename="ex99.htm",
        url="",
        fetcher=lambda _a: b"<html><body>Press release</body></html>",
        renderer=lambda _a: "Press release",
    )
    assert att.content() == b"<html><body>Press release</body></html>"
    # text() keeps its plain decode; rendered_text rides the renderer.
    assert att.text() == "<html><body>Press release</body></html>"
    assert att.rendered_text() == "Press release"

    graphic = FilingAttachment(
        attachment_id="c2",
        document_type="GRAPHIC",
        filename="chart.jpg",
        url="",
        fetcher=lambda _a: b"\xff\xd8",
    )
    assert graphic.rendered_text() is None

    bare = FilingAttachment(
        attachment_id="c3", document_type="10-K", filename="none.htm", url=""
    )
    assert bare.content() is None
    assert bare.rendered_text() is None


def _hand_built_filing() -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        primary_document_path="aapl-20230930.htm",
        attachments=_attachments(),
    )


def test_facade_attachments_matches_direct_construction() -> None:
    filing = _hand_built_filing()
    via_facade = Edgar().attachments(filing)
    direct = Attachments(filing.get_attachments())
    assert isinstance(via_facade, Attachments)
    assert list(via_facade) == list(direct)
    for picked, original in zip(via_facade, filing.attachments):
        assert picked is original
    assert _ids(via_facade.exhibits()) == ["a2", "a3", "a6", "a7", "a8"]


def test_facade_attachments_over_fast_path_filing(tmp_path: Path) -> None:
    accession = AccessionNumber.from_any("0000320193-23-000106")
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    index_html = b"""
<html>
<body>
<table summary="Document Format Files">
<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
<tr><td>1</td><td>10-K</td><td><a href="aapl-20230930.htm">aapl-20230930.htm</a></td><td>10-K</td><td>1000</td></tr>
<tr><td>2</td><td>SUBSIDIARIES</td><td><a href="ex21.htm">ex21.htm</a></td><td>EX-21.1</td><td>200</td></tr>
</table>
</body>
</html>
"""
    cache.put(
        accession=accession.raw,
        cik="320193",
        form="10-K",
        filename=f"{accession.raw}-index.html",
        content=index_html,
        content_type="text/html",
    )
    filing = FilingAggregate(
        accession=accession,
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        primary_document_path="aapl-20230930.htm",
        attachment_loader=make_attachment_loader(cache),
    )

    def projection(collection: Attachments) -> list[tuple]:
        return [(a.filename, a.sequence, a.role, a.state) for a in collection]

    via_facade = Edgar().attachments(filing)
    direct = Attachments(filing.get_attachments())
    assert projection(via_facade) == projection(direct)
    assert projection(via_facade) == [
        ("aapl-20230930.htm", 1, "primary", "not_acquired"),
        ("ex21.htm", 2, "exhibit", "not_acquired"),
    ]
