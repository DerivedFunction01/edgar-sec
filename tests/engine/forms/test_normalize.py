"""Golden-fixture regression for `normalize_document`."""

from __future__ import annotations

from edgar_sec.engine.forms.normalize import NormalizationResult, normalize_document
from edgar_sec.engine.forms.normalize import _trim_text_with_toc_span
from edgar_sec.engine.forms.cover.toc.models import TocSpan
from edgar_sec.engine.tables.protection.tags import SENTINEL_PREFIX, SENTINEL_SUFFIX
from tests.support.fixtures import fixture_path, load_fixture


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


def test_schedule_13d_and_13g_profiles_preserve_span_tables() -> None:
    label = "Number of Shares Beneficially Owned by Each Reporting Person With"
    html = (
        "<html><body><table><tr><td colspan='3' rowspan='4'>"
        f"{label}</td><td>7.</td><td>Sole Voting Power 0</td></tr>"
        "<tr><td>8.</td><td>Shared Voting Power 100</td></tr>"
        "<tr><td>9.</td><td>Sole Dispositive Power 0</td></tr>"
        "<tr><td>10.</td><td>Shared Dispositive Power 100</td></tr>"
        "</table></body></html>"
    ).encode()

    for form in ("SC 13D/A", "SCHEDULE 13G/A"):
        result = normalize_document(html, form=form)
        assert "<TABLE>" in result.text
        assert result.text.count(label) == 1
        assert all(value in result.text for value in ("7.", "8.", "9.", "10."))
        numbered_lines = [
            line
            for line in result.text.splitlines()
            if any(f"{number}." in line for number in (7, 8, 9, 10))
        ]
        assert len(numbered_lines) == 4
        assert all(
            sum(f"{number}." in line for number in (7, 8, 9, 10)) == 1
            for line in numbered_lines
        )
        assert len(result.table_geometries) == 1

    annual = normalize_document(html, form="10-K")
    assert "<TABLE>" not in annual.text
    assert annual.text.count(label) > 1


def test_normalize_empty_payload() -> None:
    res = normalize_document(b"", form="10-K")
    assert res.text == ""
    assert res.representation == "ascii"
    assert res.cover_boundary.start_line is None
    assert res.cover_boundary.end_line is None


def test_cover_fill_mark_is_canonicalized_and_resolved() -> None:
    text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\n\nFORM 10-K\n\n"
        "ACME INDUSTRIAL WIDGETS, INC.\nDelaware\n"
        "Commission File Number: 001-14103\n\n"
        "___X____ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) "
        "OF THE SECURITIES EXCHANGE ACT OF 1934\n\nPART I\n"
    )

    res = normalize_document(text.encode("utf-8"), form="10-K")

    assert "[X] ANNUAL REPORT" in res.text
    assert "___X____" not in res.text
    assert res.cover_checkmarks is not None
    assert {
        (candidate.semantic_key, candidate.known_state)
        for candidate in res.cover_checkmarks.candidates
    } == {("annual", "checked")}


def test_cover_unfilled_slot_is_not_a_checkbox() -> None:
    text = (
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\n\nFORM 10-K\n\n"
        "ACME INDUSTRIAL WIDGETS, INC.\nDelaware\n"
        "Commission File Number: 001-14103\n\n"
        "________ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) "
        "OF THE SECURITIES EXCHANGE ACT OF 1934\n\nPART I\n"
    )

    res = normalize_document(text.encode("utf-8"), form="10-K")

    assert "________ANNUAL REPORT" in res.text
    assert res.cover_checkmarks is not None
    assert res.cover_checkmarks.candidates == ()


def test_toc_offsets_match_trimmed_normalized_text() -> None:
    text = "\ncover\nTABLE OF CONTENTS\nITEM 1. BUSINESS\nITEM 2. PROPERTIES\nbody\n"
    span = TocSpan(
        start_line=2,
        end_line=5,
        start_offset=text.index("TABLE"),
        end_offset=text.index("body"),
        method="test",
        confidence=1.0,
    )

    normalized, aligned = _trim_text_with_toc_span(text, span)

    assert aligned is not None
    assert aligned.start_line == 1
    assert aligned.end_line == 4
    assert normalized[aligned.start_offset : aligned.end_offset] == (
        "TABLE OF CONTENTS\nITEM 1. BUSINESS\nITEM 2. PROPERTIES\n"
    )


def test_s1_cover_wingdings_glyphs_normalize_to_unchecked_boxes() -> None:
    """Anthropic S-1 cover excerpt: entity-quoted Wingdings 2 boxes convert."""
    path = fixture_path("document/anthropic_s1_cover_wingdings.htm")
    res = normalize_document(path.read_bytes(), form="S-1", document_path=path.name)

    assert res.family == "S-1"
    assert res.representation == "html"
    assert "£" not in res.text
    assert "&#163;" not in res.text
    assert res.text.count("[ ]") == 9
    assert res.text.count("[X]") == 1

    assert res.cover_checkmarks is not None
    states = dict(res.cover_checkmarks.hypotheses[0].states)
    assert states["rule 415"] == "unchecked"
    assert states["rule 462b"] == "unchecked"
    assert states["rule 462c"] == "unchecked"
    assert states["rule 462d"] == "unchecked"
    assert states["non_accelerated_filer"] == "checked"
