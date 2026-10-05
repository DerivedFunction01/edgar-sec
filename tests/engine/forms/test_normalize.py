"""Golden-fixture regression for `normalize_document`."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.tables.protection.tags import SENTINEL_PREFIX, SENTINEL_SUFFIX
from tests.support import load_fixture


def test_annual_10k_ascii_golden() -> None:
    data = load_fixture("document_storage/annual_10k_normalization.json")
    raw_bytes = data["source_text"].encode("utf-8")
    form = data.get("form", "10-K")
    exp = data["expectations"]

    res: NormalizationResult = normalize_document(raw_bytes, form=form)

    assert res.representation == exp["representation"]
    assert res.cover_start_detected_line == exp["cover_start_detected_line"]
    assert res.cover_boundary_detected_line == exp["cover_boundary_detected_line"]
    assert res.cover_boundary.confidence == exp["cover_boundary_confidence"]

    assert res.body_start is not None
    assert res.body_start.anchor_type == exp["body_anchor_type"]
    assert res.body_start.first_unit_line == exp["body_first_unit_line"]

    assert res.closing_span is not None
    assert res.closing_span.kind == exp["closing_kind"]
    assert res.closing_span.start_line == exp["closing_start_line"]

    assert len(res.table_geometries) == 0
    assert not exp["table_survives"]

    words = len(res.text.split())
    assert words == exp["word_count"]

    assert SENTINEL_PREFIX not in res.text
    assert SENTINEL_SUFFIX not in res.text
    assert "\x1b" not in res.text
    assert "\x00" not in res.text

    stage_names = [s.stage for s in res.stage_trace]
    assert stage_names == exp["stage_order"]
    for stage_rec in res.stage_trace:
        assert len(stage_rec.text_identity) == 64  # SHA-256 hex digest
        assert stage_rec.line_count > 0
        assert stage_rec.char_count > 0


def test_annual_10k_html_golden() -> None:
    data = load_fixture("document_storage/annual_10k_html.json")
    raw_bytes = data["source_text"].encode("utf-8")
    form = data.get("form", "10-K")
    exp = data["expectations"]

    res: NormalizationResult = normalize_document(raw_bytes, form=form)

    assert res.representation == exp["representation"]
    assert res.cover_start_detected_line == exp["cover_start_detected_line"]
    assert res.cover_boundary_detected_line == exp["cover_boundary_detected_line"]
    assert res.cover_boundary.confidence == exp["cover_boundary_confidence"]

    assert res.body_start is not None
    assert res.body_start.anchor_type == exp["body_anchor_type"]
    assert res.body_start.first_unit_line == exp["body_first_unit_line"]

    assert res.closing_span is not None
    assert res.closing_span.kind == exp["closing_kind"]
    assert res.closing_span.start_line == exp["closing_start_line"]

    assert len(res.table_geometries) == 1
    assert exp["table_survives"]
    assert "<TABLE>" in res.text
    assert "</TABLE>" in res.text
    assert "Segment" in res.text
    assert "Widgets" in res.text

    words = len(res.text.split())
    assert words == exp["word_count"]

    assert SENTINEL_PREFIX not in res.text
    assert SENTINEL_SUFFIX not in res.text

    stage_names = [s.stage for s in res.stage_trace]
    assert stage_names == exp["stage_order"]
    for stage_rec in res.stage_trace:
        assert len(stage_rec.text_identity) == 64
        assert stage_rec.line_count > 0
        assert stage_rec.char_count > 0


def test_normalize_empty_payload() -> None:
    res = normalize_document(b"", form="10-K")
    assert res.text == ""
    assert res.representation == "ascii"
    assert res.cover_boundary.start_line is None
    assert res.cover_boundary.end_line is None
    assert len(res.stage_trace) >= 1
    assert res.stage_trace[0].stage == "unpacked"
    assert res.stage_trace[0].char_count == 0


_HARD_WRAPPED = (
    b"The Registrant hereby reports the following matters in accordance with\n"
    b"the requirements of the Securities Exchange Act of 1934, as amended.\n"
    b"This paragraph continues across several hard-wrapped source lines\n"
    b"and is unwrapped into one flowing sentence.\n"
)


_PAPER_STUB = (
    b"<SEC-HEADER>\n"
    b"<DOCUMENT>\n"
    b"<TYPE>19B-4E\n"
    b"<SEQUENCE>1\n"
    b"<FILENAME>9999999997-25-001505.paper\n"
    b"<DESCRIPTION>AUTO-GENERATED PAPER DOCUMENT\n"
    b"<TEXT>\n"
    b"This document was generated as part of a paper submission.\n"
    b"Please reference the Document Control Number 25000522 for access to "
    b"the original document.\n"
    b"</TEXT>\n"
    b"</DOCUMENT>\n"
    b"</SEC-DOCUMENT>\n"
)


#: A minimal PDF whose non-ASCII bytes must survive verbatim if it is ever stored.
_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def test_no_cover_ascii_reflows_from_line_zero() -> None:
    """No cover structure means no detected body start, so reflow must still run."""
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.txt")

    assert res.reflow is not None
    assert len(res.text.splitlines()) == 1
    assert "Securities Exchange Act of 1934, as amended." in res.text


def test_cover_bearing_family_keeps_detected_body_offset() -> None:
    data = load_fixture("document_storage/annual_10k_normalization.json")
    raw_bytes = data["source_text"].encode("utf-8")

    res = normalize_document(raw_bytes, form="10-K", document_path="annual.txt")

    assert res.body_start is not None
    assert res.body_start.first_unit_line is not None
    assert res.body_start.first_unit_line > 0


def test_rendered_path_is_not_treated_as_xml() -> None:
    """An XSL rendering is named ``.xml`` but serves markup, and must not be read as XML."""
    payload = b"<HTML><BODY><TABLE><TR><TD>OWNERSHIP</TD></TR></TABLE></BODY></HTML>"

    res = normalize_document(payload, form="4", document_path="xslF345X03/doc4.xml")

    assert res.representation == "html"
    assert res.reflow is None


def test_markup_path_without_markup_is_normalized_as_text() -> None:
    """A ``.htm`` path whose bytes carry no markup is still ASCII; the payload decides."""
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.htm")

    assert res.representation == "ascii"
    assert res.reflow is None


def test_flat_xml_path_is_not_text() -> None:
    payload = b'<?xml version="1.0"?><ownershipDocument><x>1</x></ownershipDocument>'

    res = normalize_document(payload, form="4", document_path="ownership.xml")

    assert res.representation == "xml"
    assert res.reflow is None


def test_markup_route_is_not_reflowed() -> None:
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.htm")

    assert res.reflow is None


def test_paper_route_skips_form_driven_stages() -> None:
    res = normalize_document(
        _PAPER_STUB, form="REGDEX", document_path="9999999997-25-001505.paper"
    )

    assert res.representation == "ascii"
    assert [s.stage for s in res.stage_trace] == ["unpacked"]
    assert res.reflow is None
    assert res.body_start is None
    assert res.cover_boundary.method.value == "disabled"
    assert "Document Control Number 25000522" in res.text


def test_binary_route_is_refused() -> None:
    """There is no text form of a PDF, so normalization must refuse rather than invent one."""
    with pytest.raises(ValueError, match="binary"):
        normalize_document(_PDF_BYTES, form="8-K", document_path="chart.pdf")


def test_binary_refusal_names_the_route_and_the_remedy() -> None:
    """The message must tell the caller what to do, not that the route is unimplemented."""
    with pytest.raises(ValueError, match="verbatim"):
        normalize_document(_PDF_BYTES, form="8-K", document_path="chart.pdf")


def test_every_binary_suffix_is_refused() -> None:
    for suffix in (".pdf", ".gif", ".jpg"):
        with pytest.raises(ValueError):
            normalize_document(_PDF_BYTES, form="8-K", document_path=f"chart{suffix}")


def test_xhtml_path_is_markup_not_text() -> None:
    """``.xhtml`` is markup; treating it as unknown text would reflow it as prose."""
    res = normalize_document(_HARD_WRAPPED, form="REGDEX", document_path="note.xhtml")

    assert res.reflow is None
