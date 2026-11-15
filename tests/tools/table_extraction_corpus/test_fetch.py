"""Corpus fetch: declared EX-13 targets and metadata candidacy."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik
from tools.table_extraction_corpus.build import annual_stratum
from tools.table_extraction_corpus.fetch import (
    collect_exhibits,
    declared_exhibit_targets,
    exhibit_candidates,
)


def _attachment(name: str, doc_type: str, body: bytes = b"x") -> FilingAttachment:
    return FilingAttachment(
        attachment_id=name,
        document_type=doc_type,
        filename=name,
        url=f"https://example.test/{name}",
        fetcher=lambda _att, body=body: body,
    )


def _aggregate() -> FilingAggregate:
    return FilingAggregate(
        accession=AccessionNumber("0000000000-24-000001"),
        primary_cik=Cik.from_raw("1"),
        ciks=(Cik.from_raw("1"),),
        form="10-K",
        filing_date="2024-03-01",
        primary_document_path="https://example.test/acme.htm",
        attachments=(
            _attachment("acme.htm", "10-K", b"primary"),
            _attachment("ex13a.htm", "EX-13.01", b"a"),
            _attachment("ex13b.htm", "EX-13.PDF", b"b"),
            _attachment("ex13c.htm", "EX-13.(A)", b"c"),
            _attachment("ex99.htm", "EX-99.1", b"press"),
            _attachment("ex21.htm", "EX-21", b"subs"),
        ),
    )


def test_declared_targets_come_from_the_generic_declaration(
    tmp_path: Path,
) -> None:
    targets = declared_exhibit_targets("B", profiles_root=str(tmp_path))

    assert targets == ({"role": "exhibit", "type": "EX-13", "optional": True},)
    assert declared_exhibit_targets("D", profiles_root=str(tmp_path)) == ()


def test_candidacy_is_metadata_only_over_the_full_variant_family() -> None:
    candidates = exhibit_candidates(_aggregate(), ("EX-13",))

    assert [c.filename for c in candidates] == [
        "ex13a.htm",
        "ex13b.htm",
        "ex13c.htm",
    ]


def test_collect_exhibits_fetches_only_flagged_candidates() -> None:
    exhibits = collect_exhibits(_aggregate(), ("EX-13",))

    assert [e["document_name"] for e in exhibits] == [
        "ex13a.htm",
        "ex13b.htm",
        "ex13c.htm",
    ]
    assert [e["document_type"] for e in exhibits] == [
        "EX-13.01",
        "EX-13.PDF",
        "EX-13.(A)",
    ]
    assert collect_exhibits(_aggregate(), ()) == ()


def test_annual_stratum_is_the_10k_path_only() -> None:
    assert annual_stratum("10-K") == "B"
    assert annual_stratum("10-K/A") == "B"
    assert annual_stratum("10-Q") is None
    assert annual_stratum("8-K") is None


_HEADERS = b"""<DOCUMENT>
<TYPE>10-K
<SEQUENCE>1
<FILENAME>acme.htm
<TEXT>primary</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-13.1
<SEQUENCE>2
<FILENAME>ex13.htm
<TEXT>exhibit</TEXT>
</DOCUMENT>
"""


class _FakeClient:
    """Directory JSON carries icon types; headers carry real types."""

    def get_json(self, _url: str) -> dict:
        return {
            "directory": {
                "item": [
                    {"name": "acme.htm", "type": "", "size": "10"},
                    {"name": "ex13.htm", "type": "", "size": "10"},
                ]
            }
        }

    def get_bytes(self, url: str) -> bytes:
        if "index-headers" in url:
            return _HEADERS
        return b"body"


def test_aggregate_types_come_from_the_index_headers() -> None:
    from tools.table_extraction_corpus.fetch import build_aggregate

    spec = {
        "accession": "0000000000-24-000001",
        "cik": 1,
        "form": "10-K",
        "filing_date": "2024-03-01",
        "primary_document": "acme.htm",
    }
    aggregate, _source = build_aggregate(_FakeClient(), spec)  # type: ignore[arg-type]

    types = {a.filename: a.document_type for a in aggregate.get_attachments()}
    assert types == {"acme.htm": "10-K", "ex13.htm": "EX-13.1"}
    candidates = exhibit_candidates(aggregate, ("EX-13",))
    assert [c.filename for c in candidates] == ["ex13.htm"]
