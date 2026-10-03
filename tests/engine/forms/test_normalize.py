"""Golden-fixture regression for `normalize_document`."""

from __future__ import annotations

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
