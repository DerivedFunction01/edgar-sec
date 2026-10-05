"""Canonical page-artifact tokens, template ids, and sidecar metadata."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.artifacts import (
    PAGE_BREAK_TOKEN_KIND,
    REPEATING_FOOTER_TOKEN_KIND,
    REPEATING_HEADER_TOKEN_KIND,
    artifact_metadata_entry,
    build_page_artifact_metadata,
    normalize_template_text,
    note_template,
    render_page_artifact,
    template_id_for,
    token_kind_for,
)
from edgar_sec.engine.document.page_markers.models import (
    PageArtifactPolicy,
    PageBreakArtifact,
    PageMarkerKind,
)


def test_a_rendered_token_carries_the_id_and_nothing_else() -> None:
    assert render_page_artifact(PAGE_BREAK_TOKEN_KIND, 7) == "[[SEC:PAGE_BREAK id=7]]"
    assert render_page_artifact(REPEATING_HEADER_TOKEN_KIND, 0) == (
        "[[SEC:REPEATING_HEADER id=0]]"
    )


@pytest.mark.parametrize(
    ("kind", "token_kind"),
    [
        (PageMarkerKind.REPEATING_HEADER, REPEATING_HEADER_TOKEN_KIND),
        (PageMarkerKind.REPEATING_FOOTER, REPEATING_FOOTER_TOKEN_KIND),
        (PageMarkerKind.BOUNDARY, PAGE_BREAK_TOKEN_KIND),
        (PageMarkerKind.BARE_NUMBER, PAGE_BREAK_TOKEN_KIND),
        ("unknown", PAGE_BREAK_TOKEN_KIND),
    ],
)
def test_token_kind_for_falls_back_to_a_page_break(kind: str, token_kind: str) -> None:
    assert token_kind_for(kind) == token_kind


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  ABC   CORP  ", ("ABC CORP", None)),
        ("Notes page 12", ("Notes page #", 0)),
        ("Notes 12 and 34", ("Notes # and #", None)),
        ("Notes to statements 12", ("Notes to statements #", 0)),
        ("", ("", None)),
    ],
)
def test_normalization_masks_digit_runs_and_names_the_slot(
    text: str, expected: tuple[str, int | None]
) -> None:
    assert normalize_template_text(text) == expected


@pytest.mark.parametrize("text", ["F-3", "Notes -3", "Item 99A"])
def test_a_digit_run_adjacent_to_a_hyphen_or_a_word_is_not_masked(text: str) -> None:
    # The mask refuses a run touching a word character or hyphen, so an exhibit page
    # (`F-3`) and a version-stamped figure keep their digit.
    assert normalize_template_text(text) == (text, None)


def test_a_recorded_page_number_slot_is_always_the_first_replacement() -> None:
    # The slot indexes the run within the replacements list, not its position in the
    # text, so it is a "was there exactly one number" flag; the rendered text locates it.
    assert normalize_template_text("Notes to statements 12") == (
        "Notes to statements #",
        0,
    )
    assert normalize_template_text("Page 1") == ("Page #", 0)
    assert normalize_template_text("1 Page") == ("# Page", 0)


def test_multiple_digit_runs_leave_the_slot_ambiguous() -> None:
    assert normalize_template_text("Notes 12 and 34")[1] is None


def test_a_template_id_is_stable_for_the_same_normalized_text() -> None:
    assert template_id_for("abc corp") == template_id_for("abc corp")
    assert template_id_for("abc corp") != template_id_for("abc inc")
    assert len(template_id_for("abc corp")) == 16


def test_furniture_differing_only_by_page_number_lands_in_one_template() -> None:
    templates: dict = {}
    first = note_template(templates, PageMarkerKind.REPEATING_HEADER, "Page 1")
    second = note_template(templates, PageMarkerKind.REPEATING_HEADER, "Page 2")
    assert first == second
    assert templates[first]["occurrences"] == 2
    assert templates[first]["kind"] == PageMarkerKind.REPEATING_HEADER
    assert templates[first]["page_number_slot"] == 0
    assert templates[first]["rendered_text"] == "Page #"


def test_different_furniture_lands_in_different_templates() -> None:
    templates: dict = {}
    first = note_template(templates, PageMarkerKind.REPEATING_HEADER, "Page 1")
    second = note_template(templates, PageMarkerKind.REPEATING_HEADER, "Confidential")
    assert first != second
    assert len(templates) == 2


def test_a_template_id_keys_on_text_alone_so_identical_furniture_merges() -> None:
    # The id is a digest of normalized text, so an identical header and footer share one
    # entry and the first kind observed is the one recorded.
    templates: dict = {}
    template_id = note_template(templates, PageMarkerKind.REPEATING_HEADER, "Page 1")
    assert note_template(templates, PageMarkerKind.REPEATING_FOOTER, "Page 1") == (
        template_id
    )
    assert templates[template_id]["kind"] == PageMarkerKind.REPEATING_HEADER
    assert templates[template_id]["occurrences"] == 2


def test_an_unnormalizable_capture_records_nothing() -> None:
    templates: dict = {}
    assert note_template(templates, PageMarkerKind.REPEATING_HEADER, "   ") == ""
    assert templates == {}


def test_a_page_number_never_resolves_an_ambiguous_slot() -> None:
    templates: dict = {}
    template_id = note_template(
        templates, PageMarkerKind.REPEATING_HEADER, "Notes 12 and 34", page_number=34
    )
    assert templates[template_id]["page_number_slot"] is None


def test_a_metadata_entry_reports_the_artifact_span_and_removability() -> None:
    artifact = PageBreakArtifact(
        page_number=7,
        namespace="arabic",
        source="bare_number",
        coordinate_frame="text",
        source_identity="src-1",
        start=10,
        end=11,
        start_line=2,
        end_line=2,
        removable=True,
    )
    entry = artifact_metadata_entry(artifact, 1)
    assert entry == {
        "id": 1,
        "kind": "page_break",
        "page_number": 7,
        "namespace": "arabic",
        "source": "bare_number",
        "node_path": None,
        "line_span": [2, 2],
        "char_span": [10, 11],
        "template_id": None,
        "removable": True,
    }


def test_a_repeating_artifact_reports_its_own_kind() -> None:
    artifact = PageBreakArtifact(
        page_number=None,
        namespace=None,
        source="repeating_footer",
        coordinate_frame="text",
        source_identity="src-1",
    )
    assert artifact_metadata_entry(artifact, 1)["kind"] == "repeating_footer"


def test_metadata_is_ordered_so_the_same_input_yields_the_same_bytes() -> None:
    templates = {"b": {"kind": "repeating_header"}, "a": {"kind": "repeating_footer"}}
    artifacts = [
        (2, PageBreakArtifact(2, "arabic", "bare_number", "text", "src")),
        (1, PageBreakArtifact(1, "arabic", "bare_number", "text", "src")),
    ]
    metadata = build_page_artifact_metadata(
        PageArtifactPolicy.STRIP, "src", templates, artifacts
    )
    assert metadata["policy"] == "strip"
    assert metadata["source_identity"] == "src"
    assert list(metadata["templates"]) == ["a", "b"]
    assert [entry["id"] for entry in metadata["artifacts"]] == [1, 2]
